#!/usr/bin/env python3
"""
파일 병합 리네이머
여러 폴더의 이미지를 순서대로 병합 후 일괄 이름 변경
"""

import sys
import os
import re
import shutil
import zipfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog,
    QLineEdit, QComboBox, QRadioButton, QProgressBar, QGroupBox,
    QSpinBox, QCheckBox, QSplitter, QAbstractItemView, QMessageBox,
    QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt5.QtGui import QFont, QColor, QPixmap, QImage, QIcon

IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp',
    '.webp', '.tiff', '.tif', '.heic', '.avif'
}

THUMB_SIZE = 72  # 썸네일 크기 (px)


def _natural_key(s):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]


# ─────────────────────────────────────────────
#  드래그 앤 드롭 영역
# ─────────────────────────────────────────────
class DropArea(QFrame):
    folders_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFixedHeight(70)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #90CAF9;
                border-radius: 10px;
                background-color: #F3F8FF;
            }
        """)
        layout = QVBoxLayout(self)
        lbl = QLabel("📂  폴더를 여기에 드래그 앤 드롭  (여러 개 동시 가능)")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #5C8ADB; font-size: 13px; border: none; background: transparent;")
        layout.addWidget(lbl)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                QFrame {
                    border: 2px dashed #1976D2;
                    border-radius: 10px;
                    background-color: #DDEEFF;
                }
            """)

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #90CAF9;
                border-radius: 10px;
                background-color: #F3F8FF;
            }
        """)

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        folders = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if os.path.isdir(url.toLocalFile())
        ]
        if folders:
            self.folders_dropped.emit(folders)


# ─────────────────────────────────────────────
#  썸네일 로더 스레드 (비동기)
# ─────────────────────────────────────────────
class ThumbnailLoader(QThread):
    thumbnail_ready = pyqtSignal(int, object)  # index, QPixmap or None

    def __init__(self, files):
        super().__init__()
        self._files     = files
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            from PIL import Image
        except ImportError:
            return

        for i, path in enumerate(self._files):
            if self._cancelled:
                break
            try:
                img = Image.open(path)
                img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                img = img.convert('RGBA')
                data  = img.tobytes('raw', 'RGBA')
                qimg  = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
                pixmap = QPixmap.fromImage(qimg)
                self.thumbnail_ready.emit(i, pixmap)
            except Exception:
                self.thumbnail_ready.emit(i, None)


# ─────────────────────────────────────────────
#  백그라운드 작업 스레드
# ─────────────────────────────────────────────
class RenameWorker(QThread):
    progress  = pyqtSignal(int, int)
    finished  = pyqtSignal(str)
    error     = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, folders, options, output_path, as_zip, preserve_original):
        super().__init__()
        self.folders           = folders
        self.options           = options
        self.output_path       = output_path
        self.as_zip            = as_zip
        self.preserve_original = preserve_original
        self._cancelled        = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            all_files = self._collect_files()
            total = len(all_files)
            if total == 0:
                self.error.emit("처리할 이미지 파일이 없습니다.")
                return

            prefix    = self.options.get('prefix', '')
            padding   = self.options.get('padding', 3)
            start_num = self.options.get('start_num', 1)

            if self.as_zip:
                self._save_zip(all_files, prefix, padding, start_num, total)
            else:
                self._save_folder(all_files, prefix, padding, start_num, total)

            if self._cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit(f"완료!  총 {total}개 파일 처리됨\n저장 위치: {self.output_path}")
        except Exception as e:
            self.error.emit(str(e))

    def _collect_files(self):
        sort_key  = self.options.get('sort_key', 'name')
        all_files = []
        for folder in self.folders:
            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if Path(f).suffix.lower() in IMAGE_EXTENSIONS
            ]
            if sort_key == 'name':
                files.sort(key=lambda x: _natural_key(os.path.basename(x)))
            elif sort_key == 'date_modified':
                files.sort(key=os.path.getmtime)
            elif sort_key == 'date_created':
                files.sort(key=os.path.getctime)
            elif sort_key == 'size':
                files.sort(key=os.path.getsize)
            all_files.extend(files)
        return all_files

    def _make_name(self, src, index, prefix, padding):
        ext     = Path(src).suffix.lower()
        num_str = str(index).zfill(padding)
        return f"{prefix}_{num_str}{ext}" if prefix else f"{num_str}{ext}"

    def _save_folder(self, files, prefix, padding, start, total):
        os.makedirs(self.output_path, exist_ok=True)
        for i, src in enumerate(files):
            if self._cancelled:
                break
            name = self._make_name(src, start + i, prefix, padding)
            dst  = os.path.join(self.output_path, name)
            if os.path.abspath(src) != os.path.abspath(dst):
                if self.preserve_original:
                    shutil.copy2(src, dst)
                else:
                    shutil.move(src, dst)
            self.progress.emit(i + 1, total)

    def _save_zip(self, files, prefix, padding, start, total):
        output = self.output_path
        if output.lower().endswith('.zip'):
            zip_path = output
            os.makedirs(os.path.dirname(zip_path) or '.', exist_ok=True)
        else:
            # 폴더 경로로 취급 → 해당 폴더 안에 zip 저장 (폴더명.zip)
            os.makedirs(output, exist_ok=True)
            folder_name = os.path.basename(output.rstrip('/\\')) or 'output'
            zip_path = os.path.join(output, f"{folder_name}.zip")
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, src in enumerate(files):
                    if self._cancelled:
                        break
                    name = self._make_name(src, start + i, prefix, padding)
                    zf.write(src, name)
                    self.progress.emit(i + 1, total)
        finally:
            # 취소 시 불완전한 zip 파일 제거
            if self._cancelled and os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass

        if not self._cancelled and not self.preserve_original:
            for src in files:
                try:
                    os.remove(src)
                except Exception:
                    pass


# ─────────────────────────────────────────────
#  메인 윈도우
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("파일 병합 리네이머")
        self.setMinimumSize(820, 640)
        self.worker        = None
        self._thumb_loader = None

        # 미리보기 디바운스 타이머 (폴더 순서 변경 시 150ms 후 갱신)
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(150)
        self._preview_timer.timeout.connect(self._do_update_preview)

        self._build_ui()
        self._apply_style()

    # ── UI 구성 ────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setSpacing(8)
        lay.setContentsMargins(12, 12, 12, 12)

        # 드롭 영역
        self.drop_area = DropArea()
        self.drop_area.folders_dropped.connect(self.add_folders)
        lay.addWidget(self.drop_area)

        # 폴더 추가 버튼
        add_btn = QPushButton("＋  폴더 추가")
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self.browse_folder)
        lay.addWidget(add_btn)

        # ── 스플리터 (폴더 목록 | 미리보기) ──
        splitter = QSplitter(Qt.Horizontal)

        # 왼쪽 – 폴더 목록
        left = QGroupBox("폴더 목록  (드래그로 순서 변경)")
        left_lay = QVBoxLayout(left)
        self.folder_list = QListWidget()
        self.folder_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.folder_list.setDefaultDropAction(Qt.MoveAction)
        self.folder_list.model().rowsMoved.connect(self.update_preview)
        left_lay.addWidget(self.folder_list)

        row = QHBoxLayout()
        del_btn   = QPushButton("선택 삭제")
        clear_btn = QPushButton("전체 삭제")
        del_btn.clicked.connect(self.remove_selected)
        clear_btn.clicked.connect(self.clear_folders)
        row.addWidget(del_btn)
        row.addWidget(clear_btn)
        left_lay.addLayout(row)
        splitter.addWidget(left)

        # 오른쪽 – 미리보기 (썸네일 포함)
        right = QGroupBox("병합 미리보기")
        right_lay = QVBoxLayout(right)
        self.preview_list = QListWidget()
        self.preview_list.setAlternatingRowColors(True)
        self.preview_list.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self.preview_list.setSpacing(2)
        self.file_count_lbl = QLabel("파일 0개")
        self.file_count_lbl.setAlignment(Qt.AlignRight)
        right_lay.addWidget(self.preview_list)
        right_lay.addWidget(self.file_count_lbl)
        splitter.addWidget(right)

        splitter.setSizes([280, 500])
        lay.addWidget(splitter, 1)

        # ── 파일명 옵션 ──
        opt_box = QGroupBox("파일명 옵션")
        opt_lay = QHBoxLayout(opt_box)

        self.radio_num    = QRadioButton("숫자만")
        self.radio_prefix = QRadioButton("접두사 + 숫자")
        self.radio_num.setChecked(True)

        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("접두사 입력 (예: image)")
        self.prefix_input.setFixedWidth(140)
        self.prefix_input.setEnabled(False)
        self.radio_prefix.toggled.connect(self.prefix_input.setEnabled)

        pad_lbl           = QLabel("자릿수:")
        self.padding_combo = QComboBox()
        padding_items = [("1", 1), ("01", 2), ("001", 3), ("0001", 4), ("00001", 5)]
        for label, val in padding_items:
            self.padding_combo.addItem(label, val)
        self.padding_combo.setCurrentIndex(2)

        sort_lbl        = QLabel("폴더 내 정렬:")
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["파일명순", "수정일순", "생성일순", "크기순"])

        start_lbl       = QLabel("시작 번호:")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 999999)
        self.start_spin.setValue(1)

        for w in [self.radio_num, self.radio_prefix, self.prefix_input,
                  pad_lbl, self.padding_combo, sort_lbl, self.sort_combo,
                  start_lbl, self.start_spin]:
            opt_lay.addWidget(w)
        opt_lay.addStretch()
        lay.addWidget(opt_box)

        # ── 출력 설정 ──
        out_box = QGroupBox("출력 설정")
        out_lay = QHBoxLayout(out_box)

        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("저장 경로 선택...")
        browse_out = QPushButton("찾아보기")
        browse_out.clicked.connect(self.browse_output)

        self.radio_folder = QRadioButton("폴더로 저장")
        self.radio_zip    = QRadioButton("ZIP으로 저장")
        self.radio_folder.setChecked(True)

        self.preserve_chk = QCheckBox("원본 보존 (복사)")
        self.preserve_chk.setChecked(True)

        out_lay.addWidget(QLabel("저장 위치:"))
        out_lay.addWidget(self.output_input, 1)
        out_lay.addWidget(browse_out)
        out_lay.addSpacing(12)
        out_lay.addWidget(self.radio_folder)
        out_lay.addWidget(self.radio_zip)
        out_lay.addSpacing(12)
        out_lay.addWidget(self.preserve_chk)
        lay.addWidget(out_box)

        # ── 진행률 + 실행/취소 버튼 ──
        bottom = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setFormat("%v / %m")

        self.run_btn = QPushButton("실  행")
        self.run_btn.setFixedSize(90, 36)
        self.run_btn.setObjectName("runBtn")
        self.run_btn.clicked.connect(self._on_run_cancel_click)

        bottom.addWidget(self.progress_bar)
        bottom.addWidget(self.run_btn)
        lay.addLayout(bottom)

        # 옵션 변경 → 미리보기 갱신
        for sig in [self.radio_num.toggled, self.radio_prefix.toggled,
                    self.prefix_input.textChanged,
                    self.padding_combo.currentIndexChanged,
                    self.sort_combo.currentIndexChanged,
                    self.start_spin.valueChanged]:
            sig.connect(self.update_preview)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #FAFAFA; }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #DDE3EC;
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 6px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                color: #3A5A8A;
            }
            QPushButton {
                border: 1px solid #BFCFE8;
                border-radius: 5px;
                padding: 4px 10px;
                background: #EEF3FB;
            }
            QPushButton:hover { background: #D9E6F7; }
            QPushButton#runBtn {
                background: #1976D2;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
            }
            QPushButton#runBtn:hover { background: #1565C0; }
            QPushButton#runBtn:disabled { background: #90A4AE; }
            QPushButton#cancelBtn {
                background: #E53935;
                color: white;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
            }
            QPushButton#cancelBtn:hover { background: #C62828; }
            QPushButton#cancelBtn:disabled { background: #90A4AE; }
            QListWidget { border: 1px solid #DDE3EC; border-radius: 5px; }
            QListWidget::item:alternate { background: #F5F8FF; }
            QListWidget::item:selected { background: #1976D2; color: white; }
            QListWidget::item:selected:alternate { background: #1976D2; color: white; }
            QProgressBar {
                border: 1px solid #DDE3EC;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk { background: #42A5F5; border-radius: 4px; }
        """)

    # ── 폴더 관리 ──────────────────────────────
    @staticmethod
    def _collect_with_subfolders(paths: list) -> list:
        """이미지가 있는 하위 폴더까지 재귀 수집 (자연정렬)"""
        result = []
        seen = set()
        for path in paths:
            for root, dirs, files in os.walk(path):
                dirs.sort(key=_natural_key)  # 폴더명 자연정렬
                has_images = any(Path(f).suffix.lower() in IMAGE_EXTENSIONS for f in files)
                if has_images and root not in seen:
                    result.append(root)
                    seen.add(root)
        return result

    def add_folders(self, paths: list):
        expanded = self._collect_with_subfolders(paths)
        # 이미지 없는 최상위 폴더도 원래대로 추가 (하위 폴더 없는 경우 대비)
        if not expanded:
            expanded = paths
        existing = set(self._get_folder_paths())
        added = False
        for path in expanded:
            if path not in existing:
                count = self._count_images(path)
                item  = QListWidgetItem(f"📁  {os.path.basename(path)}  ({count}개)")
                item.setData(Qt.UserRole, path)
                item.setToolTip(path)
                self.folder_list.addItem(item)
                existing.add(path)
                added = True
        # 첫 폴더 등록 시 저장 위치 자동 설정
        if added and not self.output_input.text().strip():
            self.output_input.setText(paths[0])
        if added:
            self.update_preview()

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if path:
            self.add_folders([path])

    def remove_selected(self):
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))
        if self.folder_list.count() == 0:
            self.output_input.clear()
        self.update_preview()

    def clear_folders(self):
        self.folder_list.clear()
        self.preview_list.clear()
        self.file_count_lbl.setText("파일 0개")
        self.output_input.clear()

    def browse_output(self):
        if self.radio_zip.isChecked():
            path, _ = QFileDialog.getSaveFileName(self, "ZIP 저장 위치", "", "ZIP (*.zip)")
        else:
            path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택")
        if path:
            self.output_input.setText(path)

    # ── 미리보기 갱신 (디바운스 150ms) ─────────
    def update_preview(self):
        self._preview_timer.start()

    def _do_update_preview(self):
        # 기존 썸네일 로더 취소 (신호 먼저 해제하여 잔여 신호 오적용 방지)
        if self._thumb_loader and self._thumb_loader.isRunning():
            self._thumb_loader.thumbnail_ready.disconnect()
            self._thumb_loader.cancel()
            self._thumb_loader.wait()

        self.preview_list.clear()
        all_files = self._collect_files_sorted()

        prefix    = self.prefix_input.text().strip() if self.radio_prefix.isChecked() else ''
        padding   = self.padding_combo.currentData()
        start_num = self.start_spin.value()

        for i, src in enumerate(all_files):
            num_str  = str(start_num + i).zfill(padding)
            ext      = Path(src).suffix.lower()
            new_name = f"{prefix}_{num_str}{ext}" if prefix else f"{num_str}{ext}"
            folder   = os.path.basename(os.path.dirname(src))
            orig     = os.path.basename(src)
            item = QListWidgetItem(f"  {new_name}   ←   {folder}/{orig}")
            item.setSizeHint(QSize(0, THUMB_SIZE + 8))
            self.preview_list.addItem(item)

        self.file_count_lbl.setText(f"파일 {len(all_files)}개")

        # 썸네일 비동기 로드 시작
        if all_files:
            self._thumb_loader = ThumbnailLoader(all_files)
            self._thumb_loader.thumbnail_ready.connect(self._set_thumbnail)
            self._thumb_loader.start()

    def _set_thumbnail(self, index, pixmap):
        if index < self.preview_list.count() and pixmap is not None:
            self.preview_list.item(index).setIcon(QIcon(pixmap))

    # ── 실행/취소 토글 ─────────────────────────
    def _on_run_cancel_click(self):
        if self.worker and self.worker.isRunning():
            self._do_cancel()
        else:
            self.run()

    def _do_cancel(self):
        if self.worker:
            self.worker.cancel()
        self.run_btn.setEnabled(False)

    def run(self):
        folders = self._get_folder_paths()
        if not folders:
            QMessageBox.warning(self, "경고", "폴더를 먼저 추가해주세요.")
            return

        output_path = self.output_input.text().strip()
        if not output_path:
            QMessageBox.warning(self, "경고", "저장 위치를 선택해주세요.")
            return

        sort_map = ['name', 'date_modified', 'date_created', 'size']
        options  = {
            'prefix'   : self.prefix_input.text().strip() if self.radio_prefix.isChecked() else '',
            'padding'  : self.padding_combo.currentData(),
            'start_num': self.start_spin.value(),
            'sort_key' : sort_map[self.sort_combo.currentIndex()],
        }

        # 실행 버튼 → 취소 버튼으로 전환
        self.run_btn.setText("취  소")
        self.run_btn.setObjectName("cancelBtn")
        self.run_btn.setStyle(self.run_btn.style())
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0)

        self.worker = RenameWorker(
            folders=folders,
            options=options,
            output_path=output_path,
            as_zip=self.radio_zip.isChecked(),
            preserve_original=self.preserve_chk.isChecked(),
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _reset_run_btn(self):
        self.run_btn.setText("실  행")
        self.run_btn.setObjectName("runBtn")
        self.run_btn.setEnabled(True)
        self.run_btn.setStyle(self.run_btn.style())
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)

    # ── 슬롯 ───────────────────────────────────
    def _on_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_finished(self, msg):
        self._reset_run_btn()
        QMessageBox.information(self, "완료", msg)

    def _on_error(self, msg):
        self._reset_run_btn()
        QMessageBox.critical(self, "오류", f"오류 발생:\n{msg}")

    def _on_cancelled(self):
        self._reset_run_btn()
        QMessageBox.information(self, "취소됨", "작업이 취소되었습니다.")

    # ── 유틸 ───────────────────────────────────
    def _get_folder_paths(self) -> list:
        return [
            self.folder_list.item(i).data(Qt.UserRole)
            for i in range(self.folder_list.count())
        ]

    def _collect_files_sorted(self) -> list:
        sort_map = ['name', 'date_modified', 'date_created', 'size']
        sort_key = sort_map[self.sort_combo.currentIndex()]
        all_files = []
        for folder in self._get_folder_paths():
            try:
                files = [
                    os.path.join(folder, f)
                    for f in os.listdir(folder)
                    if Path(f).suffix.lower() in IMAGE_EXTENSIONS
                ]
            except Exception:
                continue
            if sort_key == 'name':
                files.sort(key=lambda x: _natural_key(os.path.basename(x)))
            elif sort_key == 'date_modified':
                files.sort(key=os.path.getmtime)
            elif sort_key == 'date_created':
                files.sort(key=os.path.getctime)
            elif sort_key == 'size':
                files.sort(key=os.path.getsize)
            all_files.extend(files)
        return all_files

    @staticmethod
    def _count_images(folder: str) -> int:
        try:
            return sum(
                1 for f in os.listdir(folder)
                if Path(f).suffix.lower() in IMAGE_EXTENSIONS
            )
        except Exception:
            return 0


# ─────────────────────────────────────────────
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
