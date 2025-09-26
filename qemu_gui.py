"""
QEMU GUI — полный интерфейс
Файл: qemu_gui.py
Требования:
  - Python 3.9+
  - pip install PySide6

Функции:
  - интерфейс из первой версии (список ВМ, редактор, консоль)
  - автоматический поиск qemu-system по архитектуре
  - выбор архитектуры (широкий список)
  - проверка выбранного qemu (`--version`)
  - запуск/остановка ВМ (поддержка вывода stdout/stderr в консоль)
  - сетевой режим: user / tap / bridge + порт-форвардинг (hostfwd)
  - опция графический / без GUI (`-nographic`)
  - создание диска через `qemu-img` (qcow2/raw)
  - сохранение конфигураций ВМ в JSON
  - лог в файл и в окно консоли

Примечание: программа запускает внешние бинарники qemu/qemu-img. Убедитесь, что они у вас установлены.
"""

import sys
import os
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from PySide6 import QtCore, QtWidgets

APP_DIR = Path.home() / ".qemu_gui"
VM_DB = APP_DIR / "vms.json"
CONFIG = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "qemu_gui.log"
APP_DIR.mkdir(exist_ok=True)

# Расширенный список архитектур
ARCH_BINARIES = [
    'i386', 'x86_64', 'arm', 'aarch64',
    'mips', 'mipsel', 'mips64', 'mips64el',
    'ppc', 'ppc64', 'ppc64le',
    'riscv32', 'riscv64',
    'sparc', 'sparc64',
    's390x'
]

NET_MODES = ['user', 'tap', 'bridge']
DISK_FORMATS = ['qcow2', 'raw']

# -------------------------- Utilities --------------------------

def log(msg: str):
    s = f"[{QtCore.QDateTime.currentDateTime().toString()}] {msg}"
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(s + "\n")
    except Exception:
        pass
    print(s)


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return default
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def find_qemu_for_arch(arch: str) -> Optional[str]:
    names = [f"qemu-system-{arch}"]
    if os.name == 'nt':
        names = [n + '.exe' for n in names]
    # try PATH
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    # try common Program Files paths on Windows
    if os.name == 'nt':
        candidates = [
            os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'), 'qemu', 'bin', names[0]),
            os.path.join(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'), 'qemu', 'bin', names[0])
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return None


def find_qemu_img() -> Optional[str]:
    name = 'qemu-img'
    if os.name == 'nt':
        name += '.exe'
    p = shutil.which(name)
    return p

# -------------------------- VM Manager --------------------------

class VMManager:
    def __init__(self):
        self.vms: Dict[str, Dict[str, Any]] = load_json(VM_DB, {})
        self.config: Dict[str, Any] = load_json(CONFIG, {})
        if 'arch' not in self.config:
            self.config['arch'] = 'x86_64'
        if 'qemu_path' not in self.config or not self.config['qemu_path']:
            self.config['qemu_path'] = find_qemu_for_arch(self.config['arch']) or ''
        if 'qemu_img' not in self.config or not self.config['qemu_img']:
            self.config['qemu_img'] = find_qemu_img() or ''
        self.processes: Dict[str, subprocess.Popen] = {}

    def save(self):
        save_json(VM_DB, self.vms)
        save_json(CONFIG, self.config)

    def add_vm(self, name: str, spec: Dict[str, Any]):
        self.vms[name] = spec
        self.save()

    def remove_vm(self, name: str):
        if name in self.vms:
            del self.vms[name]
            self.save()

    def update_vm(self, name: str, spec: Dict[str, Any]):
        self.vms[name] = spec
        self.save()

    def set_arch(self, arch: str):
        self.config['arch'] = arch
        self.config['qemu_path'] = find_qemu_for_arch(arch) or ''
        self.save()

    def set_qemu_path(self, path: str):
        self.config['qemu_path'] = path
        self.save()

    def set_qemu_img(self, path: str):
        self.config['qemu_img'] = path
        self.save()

    def build_command(self, name: str) -> List[str]:
        spec = self.vms[name]
        q = self.config.get('qemu_path') or find_qemu_for_arch(self.config.get('arch', 'x86_64')) or 'qemu-system-x86_64'
        cmd = [q]
        # memory / cpus
        cmd += ['-m', str(spec.get('memory', 1024)), '-smp', str(spec.get('cpus', 1))]
        # disk
        hdd = spec.get('hdd_path')
        if hdd:
            cmd += ['-drive', f"file={hdd},if=virtio,cache=writeback"]
        # cdrom
        iso = spec.get('iso_path')
        if iso:
            cmd += ['-cdrom', iso, '-boot', 'd']
        # display
        if not spec.get('use_gui', True):
            cmd += ['-nographic']
        # network
        net_mode = spec.get('net_mode', 'user')
        if net_mode == 'user':
            netdev = 'user'
            hostfwd = spec.get('hostfwd', '')
            if hostfwd:
                cmd += ['-netdev', f"user,id=net0,{hostfwd}", '-device', 'e1000,netdev=net0']
            else:
                cmd += ['-netdev', 'user,id=net0', '-device', 'e1000,netdev=net0']
        elif net_mode == 'tap':
            tap_name = spec.get('tap_name', 'tap0')
            cmd += ['-netdev', f"tap,id=net0,ifname={tap_name},script=no,downscript=no", '-device', 'e1000,netdev=net0']
        elif net_mode == 'bridge':
            bridge_name = spec.get('bridge_name', 'br0')
            cmd += ['-netdev', f"bridge,id=net0,br={bridge_name}", '-device', 'e1000,netdev=net0']
        # extra args
        extra = spec.get('extra_args', '')
        if extra:
            cmd += extra.split()
        return cmd

    def start_vm(self, name: str, on_stdout=None, on_stderr=None, on_exit=None):
        if name in self.processes:
            raise RuntimeError('VM already running')
        cmd = self.build_command(name)
        log('Starting VM: ' + ' '.join(cmd))
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True)
        except FileNotFoundError as e:
            log(f'Executable not found: {e}')
            raise
        self.processes[name] = p

        def pump(stream, cb):
            try:
                for line in iter(stream.readline, ''):
                    if cb:
                        cb(line)
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        def waiter():
            p.wait()
            code = p.returncode
            log(f'VM {name} exited with {code}')
            if on_exit:
                on_exit(code)
            if name in self.processes:
                del self.processes[name]

        threading.Thread(target=pump, args=(p.stdout, on_stdout), daemon=True).start()
        threading.Thread(target=pump, args=(p.stderr, on_stderr), daemon=True).start()
        threading.Thread(target=waiter, daemon=True).start()
        return p

    def stop_vm(self, name: str):
        p = self.processes.get(name)
        if not p:
            raise RuntimeError('VM not running')
        p.terminate()
        log(f'Sent terminate to {name}')


# -------------------------- GUI --------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, manager: VMManager):
        super().__init__()
        self.setWindowTitle('QEMU GUI')
        self.resize(1000, 650)
        self.manager = manager

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)

        # left column: vm list + basic controls
        left_col = QtWidgets.QVBoxLayout()
        self.vm_list = QtWidgets.QListWidget()
        left_col.addWidget(QtWidgets.QLabel('Виртуальные машины'))
        left_col.addWidget(self.vm_list)
        lbtns = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton('Добавить')
        self.remove_btn = QtWidgets.QPushButton('Удалить')
        lbtns.addWidget(self.add_btn)
        lbtns.addWidget(self.remove_btn)
        left_col.addLayout(lbtns)

        # middle: VM editor (form)
        form_layout = QtWidgets.QFormLayout()
        mid_widget = QtWidgets.QWidget()
        mid_widget.setLayout(form_layout)

        self.name_edit = QtWidgets.QLineEdit()
        self.iso_edit = QtWidgets.QLineEdit()
        self.iso_browse = QtWidgets.QPushButton('Обзор')
        self.hdd_edit = QtWidgets.QLineEdit()
        self.hdd_browse = QtWidgets.QPushButton('Обзор')
        self.mem_spin = QtWidgets.QSpinBox(); self.mem_spin.setRange(64, 65536); self.mem_spin.setValue(2048)
        self.cpus_spin = QtWidgets.QSpinBox(); self.cpus_spin.setRange(1, 64); self.cpus_spin.setValue(2)
        self.gui_check = QtWidgets.QCheckBox(); self.gui_check.setChecked(True)
        self.net_combo = QtWidgets.QComboBox(); self.net_combo.addItems(NET_MODES)
        self.hostfwd_edit = QtWidgets.QLineEdit()  # e.g. tcp::2222-:22
        self.extra_edit = QtWidgets.QLineEdit()
        self.disk_format_combo = QtWidgets.QComboBox(); self.disk_format_combo.addItems(DISK_FORMATS)
        self.disk_size_edit = QtWidgets.QLineEdit('10G')
        self.create_disk_btn = QtWidgets.QPushButton('Создать диск')

        # assemble rows
        iso_row = QtWidgets.QHBoxLayout(); iso_row.addWidget(self.iso_edit); iso_row.addWidget(self.iso_browse)
        hdd_row = QtWidgets.QHBoxLayout(); hdd_row.addWidget(self.hdd_edit); hdd_row.addWidget(self.hdd_browse)

        form_layout.addRow('Имя:', self.name_edit)
        form_layout.addRow('ISO:', iso_row)
        form_layout.addRow('HDD файл:', hdd_row)
        form_layout.addRow('Формат диска:', self.disk_format_combo)
        form_layout.addRow('Размер диска (например 10G):', self.disk_size_edit)
        form_layout.addRow(self.create_disk_btn)
        form_layout.addRow('Память (MB):', self.mem_spin)
        form_layout.addRow('CPUs:', self.cpus_spin)
        form_layout.addRow('GUI (включён):', self.gui_check)
        form_layout.addRow('Сетевой режим:', self.net_combo)
        form_layout.addRow('Port forward (hostfwd):', self.hostfwd_edit)
        form_layout.addRow('Доп. аргументы:', self.extra_edit)
        form_layout.addRow(QtWidgets.QPushButton())  # spacer

        left_col.addWidget(mid_widget)

        # right column: qemu path, arch, controls, console
        right_col = QtWidgets.QVBoxLayout()
        arch_row = QtWidgets.QHBoxLayout()
        arch_row.addWidget(QtWidgets.QLabel('Архитектура:'))
        self.arch_combo = QtWidgets.QComboBox(); self.arch_combo.addItems(ARCH_BINARIES)
        self.arch_combo.setCurrentText(self.manager.config.get('arch', 'x86_64'))
        arch_row.addWidget(self.arch_combo)
        right_col.addLayout(arch_row)

        qemu_row = QtWidgets.QHBoxLayout()
        qemu_row.addWidget(QtWidgets.QLabel('Путь к qemu:'))
        self.qemu_edit = QtWidgets.QLineEdit(self.manager.config.get('qemu_path', ''))
        self.qemu_browse = QtWidgets.QPushButton('Найти')
        qemu_row.addWidget(self.qemu_edit); qemu_row.addWidget(self.qemu_browse)
        right_col.addLayout(qemu_row)

        qimg_row = QtWidgets.QHBoxLayout()
        qimg_row.addWidget(QtWidgets.QLabel('Путь к qemu-img:'))
        self.qimg_edit = QtWidgets.QLineEdit(self.manager.config.get('qemu_img', ''))
        self.qimg_browse = QtWidgets.QPushButton('Найти')
        qimg_row.addWidget(self.qimg_edit); qimg_row.addWidget(self.qimg_browse)
        right_col.addLayout(qimg_row)

        ctrl_row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton('Запустить')
        self.stop_btn = QtWidgets.QPushButton('Остановить')
        self.check_btn = QtWidgets.QPushButton('Проверить QEMU')
        ctrl_row.addWidget(self.start_btn); ctrl_row.addWidget(self.stop_btn); ctrl_row.addWidget(self.check_btn)
        right_col.addLayout(ctrl_row)

        right_col.addWidget(QtWidgets.QLabel('Консоль:'))
        self.console = QtWidgets.QPlainTextEdit(); self.console.setReadOnly(True)
        right_col.addWidget(self.console, 1)

        # compose main layout
        layout.addLayout(left_col, 2)
        layout.addLayout(right_col, 3)

        # signals
        self.add_btn.clicked.connect(self.on_add)
        self.remove_btn.clicked.connect(self.on_remove)
        self.vm_list.itemSelectionChanged.connect(self.on_select)
        self.iso_browse.clicked.connect(self.browse_iso)
        self.hdd_browse.clicked.connect(self.browse_hdd)
        self.qemu_browse.clicked.connect(self.browse_qemu)
        self.qimg_browse.clicked.connect(self.browse_qimg)
        self.create_disk_btn.clicked.connect(self.create_disk)
        self.start_btn.clicked.connect(self.on_start)
        self.stop_btn.clicked.connect(self.on_stop)
        self.check_btn.clicked.connect(self.check_qemu)
        self.arch_combo.currentTextChanged.connect(self.on_arch_change)

        # populate list
        self.refresh_vm_list()

    # ---------------- UI helper methods ----------------
    def refresh_vm_list(self):
        self.vm_list.clear()
        for name in sorted(self.manager.vms.keys()):
            self.vm_list.addItem(name)

    def on_add(self):
        i = 1
        base = 'vm'
        while f'{base}{i}' in self.manager.vms:
            i += 1
        name = f'{base}{i}'
        spec = {
            'iso_path': '',
            'hdd_path': '',
            'memory': 2048,
            'cpus': 2,
            'use_gui': True,
            'net_mode': 'user',
            'hostfwd': '',
            'tap_name': '',
            'bridge_name': '',
            'extra_args': ''
        }
        self.manager.add_vm(name, spec)
        self.refresh_vm_list()
        items = self.vm_list.findItems(name, QtCore.Qt.MatchExactly)
        if items:
            self.vm_list.setCurrentItem(items[0])

    def on_remove(self):
        it = self.vm_list.currentItem()
        if not it:
            return
        name = it.text()
        if name in self.manager.processes:
            QtWidgets.QMessageBox.warning(self, 'Ошибка', 'Нельзя удалить запущенную ВМ')
            return
        self.manager.remove_vm(name)
        self.refresh_vm_list()

    def on_select(self):
        it = self.vm_list.currentItem()
        if not it:
            return
        name = it.text()
        spec = self.manager.vms.get(name, {})
        self.name_edit.setText(name)
        self.iso_edit.setText(spec.get('iso_path', ''))
        self.hdd_edit.setText(spec.get('hdd_path', ''))
        self.mem_spin.setValue(int(spec.get('memory', 2048)))
        self.cpus_spin.setValue(int(spec.get('cpus', 2)))
        self.gui_check.setChecked(bool(spec.get('use_gui', True)))
        self.net_combo.setCurrentText(spec.get('net_mode', 'user'))
        self.hostfwd_edit.setText(spec.get('hostfwd', ''))
        self.extra_edit.setText(spec.get('extra_args', ''))

    def browse_iso(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Выберите ISO', str(Path.home()), 'ISO Files (*.iso);;All Files (*)')
        if p:
            self.iso_edit.setText(p)

    def browse_hdd(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Файл диска (создать/выбрать)', str(Path.home() / 'disk.qcow2'), 'QCOW2 Image (*.qcow2);;Raw Image (*.img);;All Files (*)')
        if p:
            self.hdd_edit.setText(p)

    def browse_qemu(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Найдите qemu-system', str(Path.home()), 'Executable (*.exe);;All Files (*)')
        if p:
            self.qemu_edit.setText(p)
            self.manager.set_qemu_path(p)

    def browse_qimg(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Найдите qemu-img', str(Path.home()), 'Executable (*.exe);;All Files (*)')
        if p:
            self.qimg_edit.setText(p)
            self.manager.set_qemu_img(p)

    def create_disk(self):
        fmt = self.disk_format_combo.currentText()
        size = self.disk_size_edit.text().strip()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Создать диск', str(Path.home() / f'disk.{fmt}'), 'All Files (*)')
        if not path:
            return
        qimg = self.manager.config.get('qemu_img') or find_qemu_img()
        if not qimg:
            QtWidgets.QMessageBox.critical(self, 'Ошибка', 'qemu-img не найден')
            return
        args = [qimg, 'create', '-f', fmt, path, size]
        self.append_console('Запуск: ' + ' '.join(args))
        try:
            r = subprocess.run(args, capture_output=True, text=True)
            if r.returncode == 0:
                QtWidgets.QMessageBox.information(self, 'Готово', f'Диск создан: {path}')
            else:
                QtWidgets.QMessageBox.critical(self, 'Ошибка', r.stderr or r.stdout)
            self.append_console(r.stdout or r.stderr)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Ошибка', str(e))
            self.append_console(str(e))

    def append_console(self, text: str):
        QtCore.QMetaObject.invokeMethod(self.console, 'appendPlainText', QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, text))
        log(text)

    def on_start(self):
        it = self.vm_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, 'Ошибка', 'Выберите ВМ')
            return
        name = it.text()
        # save current edits into VM spec
        spec = {
            'iso_path': self.iso_edit.text().strip(),
            'hdd_path': self.hdd_edit.text().strip(),
            'memory': int(self.mem_spin.value()),
            'cpus': int(self.cpus_spin.value()),
            'use_gui': bool(self.gui_check.isChecked()),
            'net_mode': self.net_combo.currentText(),
            'hostfwd': self.hostfwd_edit.text().strip(),
            'extra_args': self.extra_edit.text().strip(),
        }
        self.manager.update_vm(name, spec)
        qpath = self.qemu_edit.text().strip()
        if qpath:
            self.manager.set_qemu_path(qpath)
        else:
            if not self.manager.config.get('qemu_path'):
                QtWidgets.QMessageBox.critical(self, 'Ошибка', 'QEMU не найден. Укажите путь.')
                return
        def on_out(line):
            self.append_console('[OUT] ' + line.rstrip())
        def on_err(line):
            self.append_console('[ERR] ' + line.rstrip())
        def on_exit(code):
            self.append_console(f'[EXIT] {code}')
        try:
            self.manager.start_vm(name, on_stdout=on_out, on_stderr=on_err, on_exit=on_exit)
            self.append_console(f'VM {name} запущена')
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(self, 'Ошибка', 'qemu-system не найден. Установите QEMU или укажите путь.')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Ошибка запуска', str(e))

    def on_stop(self):
        it = self.vm_list.currentItem()
        if not it:
            return
        name = it.text()
        try:
            self.manager.stop_vm(name)
            self.append_console(f'Отправлен сигнал остановки VM: {name}')
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, 'Ошибка', str(e))

    def check_qemu(self):
        q = self.qemu_edit.text().strip() or self.manager.config.get('qemu_path')
        if not q:
            QtWidgets.QMessageBox.critical(self, 'Ошибка', 'QEMU не найден')
            return
        try:
            r = subprocess.run([q, '--version'], capture_output=True, text=True)
            out = r.stdout or r.stderr
            self.append_console(out)
            QtWidgets.QMessageBox.information(self, 'QEMU --version', out)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Ошибка', str(e))

    def on_arch_change(self, text):
        self.manager.set_arch(text)
        # auto-set qemu path if found
        path = find_qemu_for_arch(text)
        if path:
            self.qemu_edit.setText(path)
            self.manager.set_qemu_path(path)


# -------------------------- main --------------------------

def main():
    app = QtWidgets.QApplication(sys.argv)
    manager = VMManager()
    w = MainWindow(manager)
    w.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
