# dj_mixing_gui.py
"""
AI DJ Mixing System - Interactive GUI
=====================================

A PyQt6-based graphical user interface for editing and previewing DJ mixes.
Allows real-time adjustment of transition timings with instant preview.

Features:
- Load and display mixing_plan.json transitions
- Dual waveform visualization for transition points
- Editable parameters (incoming_start, overlap, fade duration)
- Preview individual transitions
- Save updated mixing plan
- Export final mixed MP3
"""

import sys
import os
import json
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QSlider, QDoubleSpinBox,
    QPushButton, QGroupBox, QSplitter, QProgressBar, QStatusBar,
    QFileDialog, QMessageBox, QFrame, QScrollArea, QSpinBox,
    QComboBox, QTabWidget, QGridLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon

from pydub import AudioSegment
import simpleaudio as sa
import io
import wave

# Import existing modules
try:
    from mixing_engine import generate_mix
except ImportError:
    print("Warning: mixing_engine not found")

# ================= CONFIGURATION =================
SONGS_DIR = "./songs"
OUTPUT_DIR = "./output"
MIXING_PLAN_PATH = os.path.join(OUTPUT_DIR, "mixing_plan.json")
STRUCTURE_DATA_PATH = os.path.join(OUTPUT_DIR, "structure_data.json")


# ================= AUDIO PLAYER WORKER =================
class AudioPlayerWorker(QThread):
    """Background thread for audio playback with stop support"""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, audio_segment):
        super().__init__()
        self.audio_segment = audio_segment
        self.play_obj = None
        self._stop_requested = False
    
    def run(self):
        try:
            if self.audio_segment:
                # Convert to WAV format for simpleaudio
                audio = self.audio_segment.set_channels(2).set_frame_rate(44100).set_sample_width(2)
                wav_data = io.BytesIO()
                audio.export(wav_data, format='wav')
                wav_data.seek(0)
                
                # Read WAV data
                with wave.open(wav_data, 'rb') as wf:
                    audio_data = wf.readframes(wf.getnframes())
                    num_channels = wf.getnchannels()
                    bytes_per_sample = wf.getsampwidth()
                    sample_rate = wf.getframerate()
                
                # Play using simpleaudio (stoppable)
                self.play_obj = sa.play_buffer(audio_data, num_channels, bytes_per_sample, sample_rate)
                
                # Wait for playback to finish or stop
                while self.play_obj.is_playing():
                    if self._stop_requested:
                        self.play_obj.stop()
                        break
                    self.msleep(100)  # Check every 100ms
                    
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()
    
    def stop(self):
        """Stop playback immediately"""
        self._stop_requested = True
        if self.play_obj and self.play_obj.is_playing():
            self.play_obj.stop()


# ================= TIMELINE CANVAS =================
class TimelineWidget(QWidget):
    """Simple timeline view showing all tracks using Qt widgets"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mixing_plan = []
        self.setMinimumHeight(80)
        self.setStyleSheet("background-color: #1e1e1e;")
    
    def plot_timeline(self, mixing_plan):
        """Update the timeline data"""
        self.mixing_plan = mixing_plan
        self.update()
    
    def paintEvent(self, event):
        """Custom paint for timeline"""
        from PyQt6.QtGui import QPainter, QColor, QPen, QFont
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if not self.mixing_plan:
            painter.setPen(QColor('#888'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No tracks loaded")
            return
        
        colors = ['#00aaff', '#ff6600', '#00ff00', '#ff00ff', '#ffff00', '#00ffff']
        
        # Calculate total duration
        total_duration = 0
        for i, transition in enumerate(self.mixing_plan):
            if i < len(self.mixing_plan) - 1:
                next_start = self.mixing_plan[i + 1].get('incoming_start_sec', 0) or 0
                duration = max(next_start, 60)
            else:
                duration = 180
            total_duration += duration - (transition.get('overlap_duration', 8) or 8)
        
        if total_duration <= 0:
            total_duration = 600  # Default 10 minutes
        
        # Draw tracks
        width = self.width() - 20
        height = 40
        y = (self.height() - height) // 2
        x_offset = 10
        
        current_time = 0
        for i, transition in enumerate(self.mixing_plan):
            track_name = transition.get('to_track', 'Unknown')
            if not track_name:
                continue
            
            if i < len(self.mixing_plan) - 1:
                next_start = self.mixing_plan[i + 1].get('incoming_start_sec', 0) or 0
                duration = max(next_start - current_time, 60)
            else:
                duration = 180
            
            # Calculate pixel position
            x = x_offset + int((current_time / total_duration) * width)
            w = int((duration / total_duration) * width)
            
            # Draw track bar
            color = QColor(colors[i % len(colors)])
            painter.setBrush(color)
            painter.setPen(QPen(QColor('white'), 1))
            painter.drawRoundedRect(x, y, max(w, 20), height, 5, 5)
            
            # Draw track name
            painter.setPen(QColor('white'))
            font = QFont('Segoe UI', 8, QFont.Weight.Bold)
            painter.setFont(font)
            short_name = track_name[:15] + '...' if len(track_name) > 15 else track_name
            painter.drawText(x + 5, y, max(w - 10, 10), height, 
                           Qt.AlignmentFlag.AlignVCenter, short_name)
            
            current_time += duration - (transition.get('overlap_duration', 8) or 8)


# ================= TRANSITION EDITOR WIDGET =================
class TransitionEditor(QGroupBox):
    """Widget for editing transition parameters"""
    
    values_changed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__("Transition Parameters", parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #00aaff;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLabel { color: white; }
            QDoubleSpinBox, QSpinBox {
                background-color: #2b2b2b;
                color: white;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 5px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #444;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00aaff;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #00aaff;
                border-radius: 4px;
            }
        """)
        
        self.setup_ui()
    
    def setup_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(10)
        
        # Incoming Start Time
        layout.addWidget(QLabel("Incoming Start (sec):"), 0, 0)
        self.incoming_start_spin = QDoubleSpinBox()
        self.incoming_start_spin.setRange(0, 600)
        self.incoming_start_spin.setDecimals(2)
        self.incoming_start_spin.setSingleStep(0.5)
        self.incoming_start_spin.valueChanged.connect(self.on_value_changed)
        layout.addWidget(self.incoming_start_spin, 0, 1)
        
        self.incoming_start_slider = QSlider(Qt.Orientation.Horizontal)
        self.incoming_start_slider.setRange(0, 6000)  # 0-600 sec with 0.1 precision
        self.incoming_start_slider.valueChanged.connect(
            lambda v: self.incoming_start_spin.setValue(v / 10.0)
        )
        layout.addWidget(self.incoming_start_slider, 0, 2)
        
        # Transition Point
        layout.addWidget(QLabel("Transition Point (sec):"), 1, 0)
        self.transition_point_spin = QDoubleSpinBox()
        self.transition_point_spin.setRange(0, 600)
        self.transition_point_spin.setDecimals(2)
        self.transition_point_spin.setSingleStep(0.5)
        self.transition_point_spin.valueChanged.connect(self.on_value_changed)
        layout.addWidget(self.transition_point_spin, 1, 1)
        
        self.transition_point_slider = QSlider(Qt.Orientation.Horizontal)
        self.transition_point_slider.setRange(0, 6000)
        self.transition_point_slider.valueChanged.connect(
            lambda v: self.transition_point_spin.setValue(v / 10.0)
        )
        layout.addWidget(self.transition_point_slider, 1, 2)
        
        # Overlap Duration
        layout.addWidget(QLabel("Overlap Duration (sec):"), 2, 0)
        self.overlap_spin = QDoubleSpinBox()
        self.overlap_spin.setRange(1, 32)
        self.overlap_spin.setDecimals(1)
        self.overlap_spin.setSingleStep(0.5)
        self.overlap_spin.valueChanged.connect(self.on_value_changed)
        layout.addWidget(self.overlap_spin, 2, 1)
        
        self.overlap_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlap_slider.setRange(10, 320)  # 1-32 sec with 0.1 precision
        self.overlap_slider.valueChanged.connect(
            lambda v: self.overlap_spin.setValue(v / 10.0)
        )
        layout.addWidget(self.overlap_slider, 2, 2)
        
        # Fade Duration
        layout.addWidget(QLabel("Fade Duration (sec):"), 3, 0)
        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(0.5, 8)
        self.fade_spin.setDecimals(1)
        self.fade_spin.setSingleStep(0.25)
        self.fade_spin.valueChanged.connect(self.on_value_changed)
        layout.addWidget(self.fade_spin, 3, 1)
        
        self.fade_slider = QSlider(Qt.Orientation.Horizontal)
        self.fade_slider.setRange(5, 80)  # 0.5-8 sec
        self.fade_slider.valueChanged.connect(
            lambda v: self.fade_spin.setValue(v / 10.0)
        )
        layout.addWidget(self.fade_slider, 3, 2)
        
        # Transition Type
        layout.addWidget(QLabel("Transition Type:"), 4, 0)
        self.transition_type_combo = QComboBox()
        self.transition_type_combo.addItems([
            "Transition Overlap",
            "Fade In",
            "Fade Out",
            "Cut",
            "Crossfade"
        ])
        self.transition_type_combo.currentTextChanged.connect(self.on_value_changed)
        layout.addWidget(self.transition_type_combo, 4, 1, 1, 2)
        
        # BPM Info (read-only)
        layout.addWidget(QLabel("From BPM:"), 5, 0)
        self.from_bpm_label = QLabel("--")
        self.from_bpm_label.setStyleSheet("color: #ff6600; font-weight: bold;")
        layout.addWidget(self.from_bpm_label, 5, 1)
        
        layout.addWidget(QLabel("To BPM:"), 5, 2)
        self.to_bpm_label = QLabel("--")
        self.to_bpm_label.setStyleSheet("color: #00ff00; font-weight: bold;")
        layout.addWidget(self.to_bpm_label, 5, 3)
    
    def set_values(self, transition_data):
        """Set all values from transition data"""
        # Block signals to prevent triggering updates
        self.blockSignals(True)
        
        self.incoming_start_spin.setValue(transition_data.get('incoming_start_sec', 0) or 0)
        self.incoming_start_slider.setValue(int((transition_data.get('incoming_start_sec', 0) or 0) * 10))
        
        self.transition_point_spin.setValue(transition_data.get('transition_point', 0) or 0)
        self.transition_point_slider.setValue(int((transition_data.get('transition_point', 0) or 0) * 10))
        
        self.overlap_spin.setValue(transition_data.get('overlap_duration', 8) or 8)
        self.overlap_slider.setValue(int((transition_data.get('overlap_duration', 8) or 8) * 10))
        
        self.fade_spin.setValue(transition_data.get('fade_duration', 1) or 1)
        self.fade_slider.setValue(int((transition_data.get('fade_duration', 1) or 1) * 10))
        
        trans_type = transition_data.get('transition_type', 'Transition Overlap')
        idx = self.transition_type_combo.findText(trans_type)
        if idx >= 0:
            self.transition_type_combo.setCurrentIndex(idx)
        
        self.from_bpm_label.setText(str(transition_data.get('from_bpm', '--') or '--'))
        self.to_bpm_label.setText(str(transition_data.get('to_bpm', '--') or '--'))
        
        self.blockSignals(False)
    
    def get_values(self):
        """Get current values as dict"""
        return {
            'incoming_start_sec': self.incoming_start_spin.value(),
            'transition_point': self.transition_point_spin.value(),
            'overlap_duration': self.overlap_spin.value(),
            'fade_duration': self.fade_spin.value(),
            'transition_type': self.transition_type_combo.currentText()
        }
    
    def on_value_changed(self):
        """Emit signal when any value changes"""
        self.values_changed.emit()


# ================= MAIN WINDOW =================
class DJMixingGUI(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.mixing_plan = []
        self.structure_data = {}
        self.current_transition_idx = -1
        self.audio_cache = {}  # Cache loaded audio files
        self.player_thread = None
        self.unsaved_changes = False
        
        self.setup_ui()
        self.load_data()
    
    def setup_ui(self):
        """Setup the main UI"""
        self.setWindowTitle("AI DJ Mixing System - Interactive Editor")
        self.setMinimumSize(1400, 900)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #1e1e1e;
                color: white;
            }
            QListWidget {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 5px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                margin: 2px;
                border-radius: 3px;
            }
            QListWidget::item:selected {
                background-color: #00aaff;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
            QPushButton {
                background-color: #00aaff;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0088cc;
            }
            QPushButton:pressed {
                background-color: #006699;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
            QProgressBar {
                border: 1px solid #444;
                border-radius: 5px;
                text-align: center;
                background-color: #2b2b2b;
            }
            QProgressBar::chunk {
                background-color: #00aaff;
                border-radius: 4px;
            }
            QStatusBar {
                background-color: #2b2b2b;
                color: white;
            }
        """)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Top toolbar
        toolbar = self.create_toolbar()
        main_layout.addWidget(toolbar)
        
        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - Transition list
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel - Editor and waveforms
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([300, 1100])
        main_layout.addWidget(splitter, stretch=1)
        
        # Bottom - Timeline
        timeline_group = QGroupBox("Mix Timeline")
        timeline_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #00aaff;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        timeline_layout = QVBoxLayout(timeline_group)
        self.timeline_widget = TimelineWidget(self)
        timeline_layout.addWidget(self.timeline_widget)
        main_layout.addWidget(timeline_group)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready - Load a mixing plan to begin")
        
        # Progress bar in status bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.statusBar.addPermanentWidget(self.progress_bar)
    
    def create_toolbar(self):
        """Create the top toolbar"""
        toolbar = QFrame()
        toolbar.setFrameStyle(QFrame.Shape.StyledPanel)
        toolbar.setStyleSheet("QFrame { background-color: #2b2b2b; border-radius: 5px; }")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Load button
        self.load_btn = QPushButton("📂 Load Plan")
        self.load_btn.clicked.connect(self.load_mixing_plan_dialog)
        layout.addWidget(self.load_btn)
        
        # Reload button
        self.reload_btn = QPushButton("🔄 Reload")
        self.reload_btn.clicked.connect(self.load_data)
        layout.addWidget(self.reload_btn)
        
        layout.addStretch()
        
        # Preview button
        self.preview_btn = QPushButton("▶️ Preview Transition")
        self.preview_btn.clicked.connect(self.preview_transition)
        self.preview_btn.setEnabled(False)
        layout.addWidget(self.preview_btn)
        
        # Stop button
        self.stop_btn = QPushButton("⏹️ Stop")
        self.stop_btn.clicked.connect(self.stop_playback)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444;
            }
            QPushButton:hover {
                background-color: #cc3333;
            }
        """)
        layout.addWidget(self.stop_btn)
        
        layout.addStretch()
        
        # Save button
        self.save_btn = QPushButton("💾 Save Plan")
        self.save_btn.clicked.connect(self.save_mixing_plan)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #00cc66;
            }
            QPushButton:hover {
                background-color: #00aa55;
            }
        """)
        layout.addWidget(self.save_btn)
        
        # Export button
        self.export_btn = QPushButton("📤 Export Mix")
        self.export_btn.clicked.connect(self.export_mix)
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6600;
            }
            QPushButton:hover {
                background-color: #cc5500;
            }
        """)
        layout.addWidget(self.export_btn)
        
        return toolbar
    
    def create_left_panel(self):
        """Create the left panel with transition list"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Title
        title = QLabel("Transitions")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #00aaff; padding: 5px;")
        layout.addWidget(title)
        
        # Transition list
        self.transition_list = QListWidget()
        self.transition_list.currentRowChanged.connect(self.on_transition_selected)
        layout.addWidget(self.transition_list)
        
        # Info panel
        info_group = QGroupBox("Track Info")
        info_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #00aaff;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
            }
        """)
        info_layout = QVBoxLayout(info_group)
        
        self.track_info_label = QLabel("Select a transition to view details")
        self.track_info_label.setWordWrap(True)
        self.track_info_label.setStyleSheet("color: #aaa; padding: 5px;")
        info_layout.addWidget(self.track_info_label)
        
        layout.addWidget(info_group)
        
        return panel
    
    def create_right_panel(self):
        """Create the right panel with editor and waveforms"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Transition editor
        self.transition_editor = TransitionEditor()
        self.transition_editor.values_changed.connect(self.on_editor_values_changed)
        layout.addWidget(self.transition_editor)
        
        return panel
    
    def load_data(self):
        """Load mixing plan and structure data"""
        try:
            # Load mixing plan
            if os.path.exists(MIXING_PLAN_PATH):
                with open(MIXING_PLAN_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.mixing_plan = data.get('mixing_plan', [])
            else:
                self.mixing_plan = []
                self.statusBar.showMessage(f"No mixing plan found at {MIXING_PLAN_PATH}")
            
            # Load structure data
            if os.path.exists(STRUCTURE_DATA_PATH):
                with open(STRUCTURE_DATA_PATH, 'r', encoding='utf-8') as f:
                    self.structure_data = json.load(f)
            else:
                self.structure_data = {}
            
            # Update UI
            self.populate_transition_list()
            self.timeline_widget.plot_timeline(self.mixing_plan)
            
            if self.mixing_plan:
                self.save_btn.setEnabled(True)
                self.export_btn.setEnabled(True)
                self.statusBar.showMessage(f"Loaded {len(self.mixing_plan)} transitions")
            else:
                self.statusBar.showMessage("No transitions in mixing plan")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load data: {str(e)}")
            self.statusBar.showMessage(f"Error: {str(e)}")
    
    def load_mixing_plan_dialog(self):
        """Open file dialog to load a mixing plan"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Mixing Plan", OUTPUT_DIR, "JSON Files (*.json)"
        )
        if file_path:
            global MIXING_PLAN_PATH
            MIXING_PLAN_PATH = file_path
            self.load_data()
    
    def populate_transition_list(self):
        """Populate the transition list widget"""
        self.transition_list.clear()
        
        for i, transition in enumerate(self.mixing_plan):
            from_track = transition.get('from_track', 'Start')
            to_track = transition.get('to_track', 'Unknown')
            start_time = transition.get('start_time', '00:00:00')
            
            # Create display text
            if from_track:
                from_short = from_track[:15] + '...' if len(from_track) > 15 else from_track
            else:
                from_short = 'START'
            to_short = to_track[:15] + '...' if len(to_track) > 15 else to_track
            
            text = f"[{start_time}] {from_short} → {to_short}"
            
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.transition_list.addItem(item)
    
    def on_transition_selected(self, row):
        """Handle transition selection"""
        if row < 0 or row >= len(self.mixing_plan):
            return
        
        self.current_transition_idx = row
        transition = self.mixing_plan[row]
        
        # Update editor
        self.transition_editor.set_values(transition)
        
        # Update track info
        from_track = transition.get('from_track', 'None')
        to_track = transition.get('to_track', 'Unknown')
        info_text = f"""
<b>From:</b> {from_track or 'Start'}<br>
<b>To:</b> {to_track}<br>
<b>Start Time:</b> {transition.get('start_time', '--')}<br>
<b>From BPM:</b> {transition.get('from_bpm', '--')}<br>
<b>To BPM:</b> {transition.get('to_bpm', '--')}
"""
        self.track_info_label.setText(info_text)
        
        # Enable preview button
        self.preview_btn.setEnabled(True)
    
    def load_track_audio(self, track_name):
        """Load audio for a track (with caching)"""
        if track_name in self.audio_cache:
            return self.audio_cache[track_name]
        
        # Search for the file in songs directory
        for filename in os.listdir(SONGS_DIR):
            if filename.endswith(('.mp3', '.wav', '.flac')):
                # Check if filename contains track name keywords
                name_part = os.path.splitext(filename)[0].lower()
                track_lower = track_name.lower()
                
                # Simple matching - check if significant parts match
                if any(word in name_part for word in track_lower.split()[:3]):
                    try:
                        filepath = os.path.join(SONGS_DIR, filename)
                        audio = AudioSegment.from_file(filepath)
                        # Only cache first 120 seconds to save memory
                        audio = audio[:120000]
                        self.audio_cache[track_name] = audio
                        return audio
                    except Exception as e:
                        print(f"Error loading {filename}: {e}")
        
        return None
    
    def on_editor_values_changed(self):
        """Handle changes in the transition editor"""
        if self.current_transition_idx < 0:
            return
        
        # Update the mixing plan with new values
        new_values = self.transition_editor.get_values()
        transition = self.mixing_plan[self.current_transition_idx]
        
        transition['incoming_start_sec'] = new_values['incoming_start_sec']
        transition['transition_point'] = new_values['transition_point']
        transition['overlap_duration'] = new_values['overlap_duration']
        transition['fade_duration'] = new_values['fade_duration']
        transition['transition_type'] = new_values['transition_type']
        
        self.unsaved_changes = True
        self.statusBar.showMessage("Changes pending - Click Save to apply")
        
        # Update timeline
        self.timeline_widget.plot_timeline(self.mixing_plan)
    
    def preview_transition(self):
        """Preview the current transition - starts 5 seconds before incoming_start"""
        if self.current_transition_idx < 0:
            return
        
        transition = self.mixing_plan[self.current_transition_idx]
        from_track = transition.get('from_track')
        to_track = transition.get('to_track')
        
        self.statusBar.showMessage("Generating preview...")
        self.preview_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        try:
            # Load FULL audio files for accurate preview
            outgoing_audio = self.load_full_track_audio(from_track) if from_track else None
            incoming_audio = self.load_full_track_audio(to_track) if to_track else None
            
            if incoming_audio is None:
                QMessageBox.warning(self, "Warning", f"Could not load audio for: {to_track}")
                self.preview_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                return
            
            # Get transition parameters from current editor values
            transition_point = transition.get('transition_point', 0) or 0
            overlap_duration = transition.get('overlap_duration', 8) or 8
            fade_duration = transition.get('fade_duration', 1) or 1
            
            # Convert to milliseconds
            transition_point_ms = int(transition_point * 1000)
            overlap_duration_ms = int(overlap_duration * 1000)
            fade_duration_ms = int(fade_duration * 1000)
            
            # Preview starts 5 seconds BEFORE the transition point (where incoming enters)
            preview_before_ms = 5000  # 5 seconds before transition
            preview_after_ms = 10000  # 10 seconds after overlap ends
            
            if outgoing_audio:
                # Extract outgoing: 5s before transition point through end of overlap
                outgoing_start_ms = max(0, transition_point_ms - preview_before_ms)
                outgoing_end_ms = transition_point_ms + overlap_duration_ms
                outgoing_segment = outgoing_audio[outgoing_start_ms:outgoing_end_ms]
                
                # Fade out outgoing during the overlap
                outgoing_segment = outgoing_segment.fade_out(fade_duration_ms)
                
                # Extract incoming: from start of track, for overlap + 10s after
                incoming_segment = incoming_audio[:overlap_duration_ms + preview_after_ms]
                incoming_segment = incoming_segment.fade_in(fade_duration_ms)
                
                # Calculate where incoming starts in the preview
                # Incoming starts at the transition point (which is preview_before_ms into our preview)
                incoming_position_in_preview = preview_before_ms
                
                # Create preview: outgoing with incoming overlaid at the right position
                preview_audio = outgoing_segment.overlay(incoming_segment, position=incoming_position_in_preview)
                
                # Append more of incoming after the overlap ends
                remaining_incoming = incoming_audio[overlap_duration_ms:overlap_duration_ms + preview_after_ms]
                if len(remaining_incoming) > 0:
                    preview_audio = preview_audio + remaining_incoming
                
                self.statusBar.showMessage(
                    f"Preview: transition@{transition_point:.1f}s, overlap={overlap_duration:.1f}s, fade={fade_duration:.1f}s"
                )
            else:
                # First track - just play first 30 seconds
                preview_audio = incoming_audio[:30000]
                preview_audio = preview_audio.fade_in(fade_duration_ms)
                self.statusBar.showMessage("Preview: First track intro")
            
            # Play in background thread
            self.player_thread = AudioPlayerWorker(preview_audio)
            self.player_thread.finished.connect(self.on_playback_finished)
            self.player_thread.error.connect(self.on_playback_error)
            self.player_thread.start()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Preview failed: {str(e)}")
            self.preview_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
    
    def load_full_track_audio(self, track_name):
        """Load full audio for a track (not truncated, for accurate preview)"""
        if not track_name:
            return None
            
        # Search for the file in songs directory
        for filename in os.listdir(SONGS_DIR):
            if filename.endswith(('.mp3', '.wav', '.flac')):
                name_part = os.path.splitext(filename)[0].lower()
                track_lower = track_name.lower()
                
                if any(word in name_part for word in track_lower.split()[:3]):
                    try:
                        filepath = os.path.join(SONGS_DIR, filename)
                        return AudioSegment.from_file(filepath)
                    except Exception as e:
                        print(f"Error loading {filename}: {e}")
        return None

    def stop_playback(self):
        """Stop audio playback"""
        if self.player_thread:
            self.player_thread.stop()
            # Give it a moment to stop gracefully
            if self.player_thread.isRunning():
                self.player_thread.wait(500)  # Wait up to 500ms
        
        self.preview_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar.showMessage("Playback stopped")
    
    def on_playback_finished(self):
        """Handle playback completion"""
        self.preview_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar.showMessage("Preview complete")
    
    def on_playback_error(self, error_msg):
        """Handle playback error"""
        QMessageBox.warning(self, "Playback Error", error_msg)
        self.preview_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def save_mixing_plan(self):
        """Save the updated mixing plan"""
        try:
            output_data = {"mixing_plan": self.mixing_plan}
            
            with open(MIXING_PLAN_PATH, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            self.unsaved_changes = False
            self.statusBar.showMessage(f"Saved to {MIXING_PLAN_PATH}")
            QMessageBox.information(self, "Success", "Mixing plan saved successfully!")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
    
    def export_mix(self):
        """Export the final mix using mixing_engine"""
        # Ask for output path
        output_path, _ = QFileDialog.getSaveFileName(
            self, "Export Mix", os.path.join(OUTPUT_DIR, "mix.mp3"), 
            "MP3 Files (*.mp3)"
        )
        
        if not output_path:
            return
        
        # First save the current plan
        self.save_mixing_plan()
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.export_btn.setEnabled(False)
        self.statusBar.showMessage("Exporting mix... This may take a while.")
        
        # Run export in background
        self.export_thread = ExportWorker(
            MIXING_PLAN_PATH, STRUCTURE_DATA_PATH, output_path
        )
        self.export_thread.progress.connect(self.on_export_progress)
        self.export_thread.finished.connect(self.on_export_finished)
        self.export_thread.error.connect(self.on_export_error)
        self.export_thread.start()
    
    def on_export_progress(self, value):
        """Update export progress"""
        self.progress_bar.setValue(value)
    
    def on_export_finished(self, output_path):
        """Handle export completion"""
        self.progress_bar.setVisible(False)
        self.export_btn.setEnabled(True)
        self.statusBar.showMessage(f"Export complete: {output_path}")
        QMessageBox.information(self, "Success", f"Mix exported to:\n{output_path}")
    
    def on_export_error(self, error_msg):
        """Handle export error"""
        self.progress_bar.setVisible(False)
        self.export_btn.setEnabled(True)
        self.statusBar.showMessage("Export failed")
        QMessageBox.critical(self, "Export Error", error_msg)
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Save:
                self.save_mixing_plan()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ================= EXPORT WORKER =================
class ExportWorker(QThread):
    """Background worker for mix export"""
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    
    def __init__(self, mixing_plan_path, structure_path, output_path):
        super().__init__()
        self.mixing_plan_path = mixing_plan_path
        self.structure_path = structure_path
        self.output_path = output_path
    
    def run(self):
        try:
            self.progress.emit(10)
            
            # Import and run generate_mix
            from mixing_engine import generate_mix
            
            self.progress.emit(30)
            
            generate_mix(
                mixing_plan_json=self.mixing_plan_path,
                structure_json=self.structure_path,
                output_path=self.output_path
            )
            
            self.progress.emit(100)
            self.finished.emit(self.output_path)
            
        except Exception as e:
            self.error.emit(str(e))


# ================= MAIN =================
def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    # Set application-wide font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Create and show main window
    window = DJMixingGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
