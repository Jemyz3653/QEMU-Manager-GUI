#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QEMU GUI Full — single-file manager
Features:
 - Autodetect qemu-system-<arch>, qemu-img
 - Many architectures supported
 - Create disk (qemu-img), snapshots
 - Network modes (user/tap/bridge) + hostfwd
 - VNC/SPICE/nographic, extra args
 - Save/load VM profiles (JSON)
 - Themes: light / dark / gray
 - Languages: ru, en, es, zh, ja, de, pl, be
 - Optional auto-elevation (Windows UAC)
 - Logging to window + qemu_gui.log
Requirements:
 - Python 3.9+
 - pip install PySide6
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from PySide6 import QtCore, QtWidgets, QtGui

# ------------------ Config paths ------------------
HOME = Path.home()
APP_DIR = HOME / ".qemu_gui_full"
APP_DIR.mkdir(exist_ok=True)
VM_DB = APP_DIR / "vms.json"
CONF = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "qemu_gui.log"

# ------------------ Constants ------------------
ARCHES = [
    'i386', 'x86_64', 'arm', 'aarch64',
    'mips', 'mipsel', 'mips64', 'mips64el',
    'ppc', 'ppc64', 'ppc64le',
    'riscv32', 'riscv64',
    'sparc', 'sparc64',
    's390x'
]
NET_MODES = ['user', 'tap', 'bridge', 'none']
DISK_FORMATS = ['qcow2', 'raw', 'vmdk', 'vdi']
DISPLAY_MODES = ['auto', 'nographic', 'vnc', 'spice']

LANGS = {
    'ru': 'Русский',
    'en': 'English',
    'es': 'Español',
    'zh': '中文',
    'ja': '日本語',
    'de': 'Deutsch',
    'pl': 'Polski',
    'be': 'Беларуская'
}

# Minimal translations dictionary for UI strings used below
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    'title': {'ru': 'QEMU GUI — Менеджер', 'en': 'QEMU GUI — Manager', 'es': 'QEMU GUI — Gestor', 'zh': 'QEMU GUI 管理', 'ja': 'QEMU GUI マネージャ', 'de': 'QEMU GUI Manager', 'pl': 'QEMU GUI Menedżer', 'be': 'QEMU GUI — Менеджар'},
    'add_vm': {'ru': 'Добавить', 'en': 'Add', 'es': 'Añadir', 'zh': '添加', 'ja': '追加', 'de': 'Hinzufügen', 'pl': 'Dodaj', 'be': 'Дадаць'},
    'remove_vm': {'ru': 'Удалить', 'en': 'Remove', 'es': 'Eliminar', 'zh': '删除', 'ja': '削除', 'de': 'Entfernen', 'pl': 'Usuń', 'be': 'Выдаліць'},
    'run': {'ru': 'Запустить', 'en': 'Run', 'es': 'Iniciar', 'zh': '启动', 'ja': '起動', 'de': 'Starten', 'pl': 'Uruchom', 'be': 'Запусціць'},
    'stop': {'ru': 'Остановить', 'en': 'Stop', 'es': 'Detener', 'zh': '停止', 'ja': '停止', 'de': 'Stoppen', 'pl': 'Zatrzymaj', 'be': 'Спыніць'},
    'check_qemu': {'ru': 'Проверить QEMU', 'en': 'Check QEMU', 'es': 'Comprobar QEMU', 'zh': '检查 QEMU', 'ja': 'QEMU を確認', 'de': 'QEMU prüfen', 'pl': 'Sprawdź QEMU', 'be': 'Праверыць QEMU'},
    'create_disk': {'ru': 'Создать диск', 'en': 'Create disk', 'es': 'Crear disco', 'zh': '创建磁盘', 'ja': 'ディスク作成', 'de': 'Datenträger erstellen', 'pl': 'Utwórz dysk', 'be': 'Стварыць дыск'},
    'save_profile': {'ru': 'Сохранить профиль', 'en': 'Save profile', 'es': 'Guardar perfil', 'zh': '保存配置', 'ja': 'プロファイル保存', 'de': 'Profil speichern', 'pl': 'Zapisz profil', 'be': 'Захаваць профіль'},
    'load_profile': {'ru': 'Загрузить профиль', 'en': 'Load profile', 'es': 'Cargar perfil', 'zh': '加载配置', 'ja': 'プロファイル読み込み', 'de': 'Profil laden', 'pl': 'Wczytaj profil', 'be': 'Загрузіць профіль'},
    'theme': {'ru': 'Тема', 'en': 'Theme', 'es': 'Tema', 'zh': '主题', 'ja': 'テーマ', 'de': 'Thema', 'pl': 'Motyw', 'be': 'Тэма'},
    'language': {'ru': 'Язык', 'en': 'Language', 'es': 'Idioma', 'zh': '语言', 'ja': '言語', 'de': 'Sprache', 'pl': 'Język', 'be': 'Мова'},
    'log': {'ru': 'Лог', 'en': 'Log', 'es': 'Registro', 'zh': '日志', 'ja': 'ログ', 'de': 'Protokoll', 'pl': 'Dziennik', 'be': 'Лог'},
    'vm_list': {'ru': 'Виртуальные машины', 'en': 'Virtual machines', 'es': 'Máquinas virtuales', 'zh': '虚拟机', 'ja': '仮想マシン', 'de': 'Virtuelle Maschinen', 'pl': 'Maszyny wirtualne', 'be': 'Віртуальныя машыны'},
    # Add more translation keys as needed
}

def t(key: str, lang: str) -> str:
    # fetch translation or fallback
    return TRANSLATIONS.get(key, {}).get(lang, TRANSLATIONS.get(key, {}).get('en', key))

# ------------------ Utilities ------------------
def debug(msg: str):
    stamp = QtCore.QDateTime.currentDateTime().toString(QtCore.Qt.ISODate)
    line = f"[{stamp}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)

def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        debug(f"Failed to load JSON {path}")
    return default

def save_json(path: Path, data):
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        debug(f"Failed to save JSON {path}: {e}")

def find_qemu_for_arch(arch: str) -> Optional[str]:
    base = f"qemu-system-{arch}"
    # Windows: try exe variants
    candidates = []
    if os.name == 'nt':
        names = [base + ".exe", base]
    else:
        names = [base]
    # first PATH
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    # then common locations
    if os.name == 'nt':
        pfs = [os.environ.get('ProgramFiles', r"C:\Program Files"), os.environ.get('ProgramFiles(x86)', r"C:\Program Files (x86)")]
        for pf in pfs:
            candidates += [
                os.path.join(pf, "qemu", "bin", names[0]),
                os.path.join(pf, "qemu", names[0]),
                os.path.join(pf, "qemu-w64", "bin", names[0]),
                os.path.join(pf, "qemu-w64", names[0])
            ]
        candidates.append(os.path.join(os.getcwd(), names[0]))
    else:
        for p in ['/usr/bin', '/usr/local/bin', '/snap/bin', '/opt/qemu/bin']:
            candidates.append(os.path.join(p, names[0]))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None

def find_qemu_img() -> Optional[str]:
    name = "qemu-img.exe" if os.name == 'nt' else "qemu-img"
    p = shutil.which(name)
    if p:
        return p
    if os.name == 'nt':
        pfs = [os.environ.get('ProgramFiles', r"C:\Program Files"), os.environ.get('ProgramFiles(x86)', r"C:\Program Files (x86)")]
        for pf in pfs:
            c = os.path.join(pf, "qemu", "bin", "qemu-img.exe")
            if os.path.isfile(c):
                return c
    return None

# ------------------ VM Manager ------------------
class VMManager:
    def __init__(self):
        self.vms: Dict[str, Dict[str, Any]] = load_json(VM_DB, {})
        self.config: Dict[str, Any] = load_json(CONF, {})
        self.processes: Dict[str, subprocess.Popen] = {}
        # defaults
        self.config.setdefault('lang', 'ru')
        self.config.setdefault('theme', 'light')
        self.config.setdefault('arch', 'x86_64')
        self.config.setdefault('qemu_path', '')
        self.config.setdefault('qemu_img', '')
        self.config.setdefault('auto_elevate', False)
        if not self.config['qemu_path']:
            self.config['qemu_path'] = find_qemu_for_arch(self.config['arch']) or ''
        if not self.config['qemu_img']:
            self.config['qemu_img'] = find_qemu_img() or ''
        self.save()

    def save(self):
        save_json(VM_DB, self.vms)
        save_json(CONF, self.config)

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

    def build_command(self, name: str) -> List[str]:
        if name not in self.vms:
            raise RuntimeError("VM not found")
        spec = self.vms[name]
        qemu = self.config.get('qemu_path') or find_qemu_for_arch(spec.get('arch', self.config.get('arch','x86_64'))) or 'qemu-system-x86_64'
        cmd = [qemu]
        # memory & cpus
        cmd += ['-m', str(spec.get('memory', 2048)), '-smp', str(spec.get('cpus', 2))]
        # cpu model if set
        cpu_model = spec.get('cpu_model', '')
        if cpu_model:
            cmd += ['-cpu', cpu_model]
        # drives
        hdd = spec.get('hdd_path', '')
        if hdd:
            # default virtio for good perf (user can override in extra_args)
            cmd += ['-drive', f"file={hdd},if=virtio,cache=writeback"]
        iso = spec.get('iso_path', '')
        if iso:
            cmd += ['-cdrom', iso, '-boot', 'd']
        # display
        disp = spec.get('display','auto')
        if disp == 'nographic':
            cmd += ['-nographic']
        elif disp == 'vnc':
            vnc = spec.get('vnc', ':0')
            # qemu expects :display or tcp:host:port? usual usage: -vnc :0
            if vnc.startswith(':'):
                cmd += ['-vnc', vnc]
            else:
                cmd += ['-vnc', ':' + vnc]
        elif disp == 'spice':
            spice_port = spec.get('spice_port', 5930)
            cmd += ['-spice', f"port={spice_port},disable-ticketing"]
        # network
        net = spec.get('net_mode','user')
        if net == 'user':
            hostfwd = spec.get('hostfwd','')
            if hostfwd:
                cmd += ['-netdev', f"user,id=net0,{hostfwd}", '-device', 'e1000,netdev=net0']
            else:
                cmd += ['-netdev', 'user,id=net0', '-device', 'e1000,netdev=net0']
        elif net == 'tap':
            ifname = spec.get('tap_name','tap0')
            cmd += ['-netdev', f"tap,id=net0,ifname={ifname},script=no,downscript=no", '-device', 'e1000,netdev=net0']
        elif net == 'bridge':
            br = spec.get('bridge_name','br0')
            cmd += ['-netdev', f"bridge,id=net0,br={br}", '-device', 'e1000,netdev=net0']
        # devices extras
        # usb passthrough or other device flags expected in extra_args
        extra = spec.get('extra_args','')
        if extra:
            cmd += extra.split()
        return cmd

    def start_vm(self, name: str, on_stdout=None, on_stderr=None, on_exit=None):
        if name in self.processes:
            raise RuntimeError("VM already running")
        cmd = self.build_command(name)
        debug(f"Starting VM: {' '.join(cmd)}")
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True)
        except FileNotFoundError as e:
            debug(f"Start failed: {e}")
            raise
        self.processes[name] = p

        def pump(stream, cb):
            try:
                for line in iter(stream.readline, ''):
                    if line == '':
                        break
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
            debug(f"VM {name} exited with {code}")
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
            raise RuntimeError("VM not running")
        p.terminate()
        debug(f"Terminate sent to VM {name}")

# ------------------ Admin helpers ------------------
def is_admin() -> bool:
    if os.name != 'nt':
        try:
            return os.geteuid() == 0
        except Exception:
            return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def run_as_admin(argv=None) -> bool:
    """Relaunch the script as admin (Windows). Returns True if request made."""
    if os.name != 'nt':
        return False
    import ctypes
    if argv is None:
        argv = sys.argv
    params = " ".join([f'"{a}"' for a in argv[1:]])
    executable = sys.executable
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, f'"{argv[0]}" {params}', None, 1)
        return ret > 32
    except Exception as e:
        debug(f"run_as_admin failed: {e}")
        return False

# ------------------ GUI ------------------
class QemuGUIApp(QtWidgets.QMainWindow):
    def __init__(self, manager: VMManager):
        super().__init__()
        self.manager = manager
        self.lang = manager.config.get('lang','ru')
        self.theme = manager.config.get('theme','light')
        self.setWindowTitle(t('title', self.lang))
        self.resize(1200, 760)

        # central layout
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        h = QtWidgets.QHBoxLayout(central)

        # left: VM list + add/remove buttons
        left_v = QtWidgets.QVBoxLayout()
        left_v.addWidget(QtWidgets.QLabel(t('vm_list', self.lang)))
        self.vm_list = QtWidgets.QListWidget()
        left_v.addWidget(self.vm_list)
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_add = QtWidgets.QPushButton(t('add_vm', self.lang))
        self.btn_remove = QtWidgets.QPushButton(t('remove_vm', self.lang))
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_remove)
        left_v.addLayout(btn_row)
        # profile save/load
        prof_row = QtWidgets.QHBoxLayout()
        self.btn_save_profile = QtWidgets.QPushButton(t('save_profile', self.lang))
        self.btn_load_profile = QtWidgets.QPushButton(t('load_profile', self.lang))
        prof_row.addWidget(self.btn_save_profile)
        prof_row.addWidget(self.btn_load_profile)
        left_v.addLayout(prof_row)

        h.addLayout(left_v, 2)

        # middle: tabs
        mid_v = QtWidgets.QVBoxLayout()
        self.tabs = QtWidgets.QTabWidget()
        mid_v.addWidget(self.tabs)

        # Tab: Main
        tab_main = QtWidgets.QWidget()
        form_main = QtWidgets.QFormLayout(tab_main)

        self.edit_name = QtWidgets.QLineEdit()
        self.combo_arch = QtWidgets.QComboBox(); self.combo_arch.addItems(ARCHES); self.combo_arch.setCurrentText(self.manager.config.get('arch','x86_64'))
        self.edit_qemu = QtWidgets.QLineEdit(self.manager.config.get('qemu_path',''))
        self.btn_browse_qemu = QtWidgets.QPushButton("...")
        qemu_row = QtWidgets.QHBoxLayout(); qemu_row.addWidget(self.edit_qemu); qemu_row.addWidget(self.btn_browse_qemu)

        self.spin_mem = QtWidgets.QSpinBox(); self.spin_mem.setRange(128, 65536); self.spin_mem.setValue(2048)
        self.spin_cpus = QtWidgets.QSpinBox(); self.spin_cpus.setRange(1, 64); self.spin_cpus.setValue(2)
        self.edit_cpu_model = QtWidgets.QLineEdit("qemu64")  # e.g. host, qemu64, kvm64
        self.display_combo = QtWidgets.QComboBox(); self.display_combo.addItems(DISPLAY_MODES)
        self.combo_lang = QtWidgets.QComboBox(); self.combo_lang.addItems([f"{k} - {v}" for k,v in LANGS.items()])
        # place main fields
        form_main.addRow("Name:", self.edit_name)
        form_main.addRow(t('arch', self.lang)+":", self.combo_arch)
        form_main.addRow(t('qemu_bin', self.lang)+":", qemu_row)
        form_main.addRow("RAM (MB):", self.spin_mem)
        form_main.addRow("CPUs:", self.spin_cpus)
        form_main.addRow("CPU model:", self.edit_cpu_model)
        form_main.addRow("Display:", self.display_combo)
        form_main.addRow(t('language', self.lang)+":", self.combo_lang)

        self.tabs.addTab(tab_main, "Main")

        # Tab: Disks
        tab_disks = QtWidgets.QWidget()
        form_disk = QtWidgets.QFormLayout(tab_disks)
        self.edit_hdd = QtWidgets.QLineEdit()
        self.btn_browse_hdd = QtWidgets.QPushButton("...")
        hdd_row = QtWidgets.QHBoxLayout(); hdd_row.addWidget(self.edit_hdd); hdd_row.addWidget(self.btn_browse_hdd)
        self.edit_iso = QtWidgets.QLineEdit()
        self.btn_browse_iso = QtWidgets.QPushButton("...")
        iso_row = QtWidgets.QHBoxLayout(); iso_row.addWidget(self.edit_iso); iso_row.addWidget(self.btn_browse_iso)
        self.combo_disk_format = QtWidgets.QComboBox(); self.combo_disk_format.addItems(DISK_FORMATS)
        self.edit_disk_size = QtWidgets.QLineEdit("10G")
        self.btn_create_disk = QtWidgets.QPushButton(t('create_disk', self.lang))
        form_disk.addRow("HDD file:", hdd_row)
        form_disk.addRow("ISO:", iso_row)
        form_disk.addRow("Disk format:", self.combo_disk_format)
        form_disk.addRow("Disk size:", self.edit_disk_size)
        form_disk.addRow("", self.btn_create_disk)
        self.tabs.addTab(tab_disks, "Disks")

        # Tab: Network
        tab_net = QtWidgets.QWidget()
        fnet = QtWidgets.QFormLayout(tab_net)
        self.combo_net = QtWidgets.QComboBox(); self.combo_net.addItems(NET_MODES)
        self.edit_hostfwd = QtWidgets.QLineEdit(); self.edit_hostfwd.setPlaceholderText("tcp::2222-:22")
        self.edit_tap = QtWidgets.QLineEdit("tap0")
        self.edit_bridge = QtWidgets.QLineEdit("br0")
        fnet.addRow("Net mode:", self.combo_net)
        fnet.addRow("Host forward:", self.edit_hostfwd)
        fnet.addRow("TAP name:", self.edit_tap)
        fnet.addRow("Bridge name:", self.edit_bridge)
        self.tabs.addTab(tab_net, "Network")

        # Tab: Devices
        tab_dev = QtWidgets.QWidget()
        fdev = QtWidgets.QFormLayout(tab_dev)
        self.chk_usb = QtWidgets.QCheckBox("USB passthrough (requires extra args)")
        self.combo_video = QtWidgets.QComboBox(); self.combo_video.addItems(["std","qxl","virtio","none"])
        self.chk_nographic = QtWidgets.QCheckBox("nographic")
        self.edit_vnc = QtWidgets.QLineEdit(); self.edit_vnc.setPlaceholderText(":0 or :1")
        self.edit_extra = QtWidgets.QLineEdit()
        self.edit_extra.setPlaceholderText("Extra QEMU args (raw)")
        fdev.addRow("", self.chk_usb)
        fdev.addRow("Video:", self.combo_video)
        fdev.addRow("", self.chk_nographic)
        fdev.addRow("VNC/SPICE:", self.edit_vnc)
        fdev.addRow("Extra args:", self.edit_extra)
        self.tabs.addTab(tab_dev, "Devices")

        # Tab: Snapshots
        tab_snap = QtWidgets.QWidget()
        v_snap = QtWidgets.QVBoxLayout(tab_snap)
        self.edit_snap_name = QtWidgets.QLineEdit("snap1")
        self.btn_save_snap = QtWidgets.QPushButton("Save snapshot (qemu-img)")
        v_snap.addWidget(QtWidgets.QLabel("Creates a qcow2 overlay based on base image"))
        v_snap.addWidget(QtWidgets.QLabel("Snapshot name:"))
        v_snap.addWidget(self.edit_snap_name)
        v_snap.addWidget(self.btn_save_snap)
        self.tabs.addTab(tab_snap, "Snapshots")

        # Tab: Advanced
        tab_adv = QtWidgets.QWidget()
        vadv = QtWidgets.QVBoxLayout(tab_adv)
        self.edit_manual = QtWidgets.QTextEdit()
        self.edit_manual.setPlaceholderText("Manual extra qemu command-line (appended after constructed args)")
        vadv.addWidget(QtWidgets.QLabel("Manual extra args (one line)"))
        vadv.addWidget(self.edit_manual)
        self.tabs.addTab(tab_adv, "Advanced")

        mid_v.addWidget(self.tabs)
        h.addLayout(mid_v, 6)

        # right: actions, qemu-img, themes, language, console
        right_v = QtWidgets.QVBoxLayout()

        # qemu-img path
        qimg_row = QtWidgets.QHBoxLayout()
        self.edit_qemu_img = QtWidgets.QLineEdit(self.manager.config.get('qemu_img',''))
        self.btn_browse_qimg = QtWidgets.QPushButton("...")
        qimg_row.addWidget(QtWidgets.QLabel("qemu-img:"))
        qimg_row.addWidget(self.edit_qemu_img)
        qimg_row.addWidget(self.btn_browse_qimg)
        right_v.addLayout(qimg_row)

        # run / stop / check
        run_row = QtWidgets.QHBoxLayout()
        self.btn_run = QtWidgets.QPushButton(t('run', self.lang))
        self.btn_stop = QtWidgets.QPushButton(t('stop', self.lang))
        self.btn_check = QtWidgets.QPushButton(t('check_qemu', self.lang))
        run_row.addWidget(self.btn_run); run_row.addWidget(self.btn_stop); run_row.addWidget(self.btn_check)
        right_v.addLayout(run_row)

        # Theme + Language + Elevate
        row_theme = QtWidgets.QHBoxLayout()
        row_theme.addWidget(QtWidgets.QLabel(t('theme', self.lang)+":"))
        self.combo_theme = QtWidgets.QComboBox(); self.combo_theme.addItems(['light','dark','gray'])
        row_theme.addWidget(self.combo_theme)
        right_v.addLayout(row_theme)

        row_lang = QtWidgets.QHBoxLayout()
        row_lang.addWidget(QtWidgets.QLabel(t('language', self.lang)+":"))
        self.combo_lang_simple = QtWidgets.QComboBox()
        self.combo_lang_simple.addItems([f"{k} - {v}" for k,v in LANGS.items()])
        row_lang.addWidget(self.combo_lang_simple)
        right_v.addLayout(row_lang)

        self.chk_auto_elev = QtWidgets.QCheckBox("Auto-elevate on start (Windows UAC)")
        self.chk_auto_elev.setChecked(self.manager.config.get('auto_elevate', False))
        right_v.addWidget(self.chk_auto_elev)

        # console / log
        right_v.addWidget(QtWidgets.QLabel(t('log', self.lang)))
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        right_v.addWidget(self.console, 1)

        h.addLayout(right_v, 4)

        # connect signals
        self.btn_add.clicked.connect(self.on_add_vm)
        self.btn_remove.clicked.connect(self.on_remove_vm)
        self.btn_save_profile.clicked.connect(self.on_save_profile)
        self.btn_load_profile.clicked.connect(self.on_load_profile)
        self.vm_list.itemSelectionChanged.connect(self.on_select_vm)

        self.btn_browse_qemu.clicked.connect(self.on_browse_qemu)
        self.btn_browse_qimg.clicked.connect(self.on_browse_qimg)
        self.btn_browse_hdd.clicked.connect(self.on_browse_hdd)
        self.btn_browse_iso.clicked.connect(self.on_browse_iso)
        self.btn_create_disk.clicked.connect(self.on_create_disk)

        self.btn_run.clicked.connect(self.on_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_check.clicked.connect(self.on_check)

        self.combo_arch.currentIndexChanged.connect(self.on_arch_changed)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        self.combo_lang.currentIndexChanged.connect(self.on_lang_changed)
        self.combo_lang_simple.currentIndexChanged.connect(self.on_lang_simple_changed)

        self.btn_save_snap.clicked.connect(self.on_save_snapshot)

        # initialize
        self.refresh_vm_list()
        self.apply_theme(self.manager.config.get('theme','light'))
        # set language selection
        self.set_language(self.manager.config.get('lang','ru'))

    # --------- UI helpers ----------
    def append_console(self, text: str):
        QtCore.QMetaObject.invokeMethod(self.console, "appendPlainText", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, text))
        debug(text)

    def refresh_vm_list(self):
        self.vm_list.clear()
        for name in sorted(self.manager.vms.keys()):
            self.vm_list.addItem(name)

    # --------- Actions ----------
    def on_add_vm(self):
        i = 1
        base = "vm"
        while f"{base}{i}" in self.manager.vms:
            i += 1
        name = f"{base}{i}"
        spec = {
            'name': name,
            'arch': self.combo_arch.currentText(),
            'iso_path': '',
            'hdd_path': '',
            'memory': 2048,
            'cpus': 2,
            'cpu_model': 'qemu64',
            'display': 'auto',
            'net_mode': 'user',
            'hostfwd': '',
            'tap_name': 'tap0',
            'bridge_name': 'br0',
            'extra_args': '',
            'vnc': ':0',
            'spice_port': 5930
        }
        self.manager.add_vm(name, spec)
        self.refresh_vm_list()
        # select
        items = self.vm_list.findItems(name, QtCore.Qt.MatchExactly)
        if items:
            self.vm_list.setCurrentItem(items[0])

    def on_remove_vm(self):
        it = self.vm_list.currentItem()
        if not it:
            return
        name = it.text()
        if name in self.manager.processes:
            QtWidgets.QMessageBox.warning(self, "Error", "Cannot remove running VM")
            return
        self.manager.remove_vm(name)
        self.refresh_vm_list()

    def on_select_vm(self):
        it = self.vm_list.currentItem()
        if not it:
            return
        name = it.text()
        spec = self.manager.vms.get(name, {})
        self.edit_name.setText(spec.get('name', name))
        self.combo_arch.setCurrentText(spec.get('arch', self.combo_arch.currentText()))
        self.edit_qemu.setText(self.manager.config.get('qemu_path',''))
        self.spin_mem.setValue(int(spec.get('memory', 2048)))
        self.spin_cpus.setValue(int(spec.get('cpus', 2)))
        self.edit_cpu_model.setText(spec.get('cpu_model','qemu64'))
        self.display_combo.setCurrentText(spec.get('display','auto'))
        self.edit_hdd.setText(spec.get('hdd_path',''))
        self.edit_iso.setText(spec.get('iso_path',''))
        self.combo_net.setCurrentText(spec.get('net_mode','user'))
        self.edit_hostfwd.setText(spec.get('hostfwd',''))
        self.edit_tap.setText(spec.get('tap_name','tap0'))
        self.edit_bridge.setText(spec.get('bridge_name','br0'))
        self.edit_extra.setText(spec.get('extra_args',''))
        self.edit_vnc.setText(spec.get('vnc',':0'))
        self.edit_qemu_img.setText(self.manager.config.get('qemu_img',''))

    def on_browse_qemu(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select qemu-system executable", str(Path.home()))
        if p:
            self.edit_qemu.setText(p)
            self.manager.config['qemu_path'] = p
            self.manager.save()

    def on_browse_qimg(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select qemu-img executable", str(Path.home()))
        if p:
            self.edit_qemu_img.setText(p)
            self.manager.config['qemu_img'] = p
            self.manager.save()

    def on_browse_hdd(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select/Create HDD", str(Path.home() / "disk.qcow2"))
        if p:
            self.edit_hdd.setText(p)

    def on_browse_iso(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select ISO", str(Path.home()), "ISO Files (*.iso)")
        if p:
            self.edit_iso.setText(p)

    def on_create_disk(self):
        fmt = self.combo_disk_format.currentText() if hasattr(self, 'combo_disk_format') else 'qcow2'
        size = self.edit_disk_size.text() if hasattr(self, 'edit_disk_size') else '10G'
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Create disk", str(Path.home() / f"disk.{fmt}"))
        if not p:
            return
        qimg = self.manager.config.get('qemu_img') or find_qemu_img()
        if not qimg:
            QtWidgets.QMessageBox.critical(self, "Error", "qemu-img not found")
            return
        args = [qimg, 'create', '-f', fmt, p, size]
        self.append_console("Run: " + " ".join(args))
        try:
            r = subprocess.run(args, capture_output=True, text=True)
            self.append_console(r.stdout or r.stderr)
            if r.returncode == 0:
                QtWidgets.QMessageBox.information(self, "Done", f"Disk created: {p}")
            else:
                QtWidgets.QMessageBox.critical(self, "Error", r.stderr or r.stdout)
        except Exception as e:
            self.append_console(str(e))
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_run(self):
        it = self.vm_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "Error", "Select VM")
            return
        name = it.text()
        # gather current UI state into spec
        spec = {
            'name': self.edit_name.text().strip() or name,
            'arch': self.combo_arch.currentText(),
            'qemu': self.edit_qemu.text().strip(),
            'qemu_img': self.edit_qemu_img.text().strip(),
            'memory': int(self.spin_mem.value()),
            'cpus': int(self.spin_cpus.value()),
            'cpu_model': self.edit_cpu_model.text().strip(),
            'display': self.display_combo.currentText(),
            'iso_path': self.edit_iso.text().strip(),
            'hdd_path': self.edit_hdd.text().strip(),
            'net_mode': self.combo_net.currentText(),
            'hostfwd': self.edit_hostfwd.text().strip(),
            'tap_name': self.edit_tap.text().strip(),
            'bridge_name': self.edit_bridge.text().strip(),
            'extra_args': self.edit_extra.text().strip() + " " + (self.edit_manual.toPlainText().strip().replace("\n"," ")),
            'vnc': self.edit_vnc.text().strip(),
            'spice_port': 5930
        }
        # save into manager
        self.manager.update_vm(name, spec)
        # update manager config qemu paths if given
        q = spec.get('qemu','').strip()
        if q:
            self.manager.config['qemu_path'] = q
            self.manager.save()
        else:
            if not self.manager.config.get('qemu_path'):
                QtWidgets.QMessageBox.critical(self, "Error", "QEMU not found; set path")
                return
        # try start
        def outcb(line): self.append_console("[OUT] " + line.rstrip())
        def errcb(line): self.append_console("[ERR] " + line.rstrip())
        def exitcb(code): self.append_console(f"[EXIT] {code}")
        try:
            self.manager.start_vm(name, on_stdout=outcb, on_stderr=errcb, on_exit=exitcb)
            self.append_console(f"VM {name} started")
        except FileNotFoundError as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Executable not found: {e}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_stop(self):
        it = self.vm_list.currentItem()
        if not it:
            return
        name = it.text()
        try:
            self.manager.stop_vm(name)
            self.append_console(f"Stop sent to {name}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", str(e))

    def on_check(self):
        exe = self.edit_qemu.text().strip() or self.manager.config.get('qemu_path')
        if not exe:
            QtWidgets.QMessageBox.critical(self, "Error", "QEMU not found")
            return
        try:
            r = subprocess.run([exe, '--version'], capture_output=True, text=True)
            out = r.stdout or r.stderr
            self.append_console(out)
            QtWidgets.QMessageBox.information(self, "QEMU --version", out)
        except Exception as e:
            self.append_console(str(e))
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_arch_changed(self, arch_text):
        found = find_qemu_for_arch(arch_text)
        if found:
            self.edit_qemu.setText(found)
            self.manager.config['qemu_path'] = found
            self.manager.save()

    def on_theme_changed(self, idx):
        theme = self.combo_theme.currentText()
        self.apply_theme(theme)
        self.manager.config['theme'] = theme
        self.manager.save()

    def apply_theme(self, theme: str):
        self.theme = theme
        if theme == 'light':
            self.setStyleSheet("")
        elif theme == 'dark':
            self.setStyleSheet("""
                QWidget{ background-color: #2b2b2b; color: #eaeaea; }
                QPushButton{ background-color: #3a3a3a; color: #fff; border: 1px solid #555; padding:4px; }
                QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox { background-color: #222; color: #eee; border: 1px solid #444; }
            """)
        elif theme == 'gray':
            self.setStyleSheet("""
                QWidget{ background-color: #8a8a8a; color: #ffffff; }
                QPushButton{ background-color: #6f6f6f; color: #fff; }
            """)

    def on_lang_changed(self, idx):
        # combo_lang contains items like "ru - Русский", take prefix
        s = self.combo_lang.currentText()
        code = s.split(' - ')[0] if ' - ' in s else s
        self.set_language(code)

    def on_lang_simple_changed(self, idx):
        s = self.combo_lang_simple.currentText()
        code = s.split(' - ')[0] if ' - ' in s else s
        self.set_language(code)

    def set_language(self, code: str):
        if code not in LANGS:
            return
        self.lang = code
        self.manager.config['lang'] = code
        self.manager.save()
        # apply translated strings to main static elements
        self.setWindowTitle(t('title', self.lang))
        self.btn_add.setText(t('add_vm', self.lang))
        self.btn_remove.setText(t('remove_vm', self.lang))
        self.btn_run.setText(t('run', self.lang))
        self.btn_stop.setText(t('stop', self.lang))
        self.btn_check.setText(t('check_qemu', self.lang))
        self.btn_create_disk.setText(t('create_disk', self.lang))
        self.btn_save_profile.setText(t('save_profile', self.lang))
        self.btn_load_profile.setText(t('load_profile', self.lang))
        # minimal: change labels for theme/lang in right pane handled by reloading
        self.append_console(f"Language switched to {LANGS.get(code,code)} (partial)")

    def on_save_profile(self):
        # save current edited VM as profile (json)
        it = self.vm_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "Error", "Select VM")
            return
        name = it.text()
        spec = self.manager.vms.get(name, {})
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save profile", str(APP_DIR / (name + ".json")), "JSON files (*.json)")
        if not p:
            return
        try:
            Path(p).write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding='utf-8')
            QtWidgets.QMessageBox.information(self, "Saved", f"Profile saved: {p}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def on_load_profile(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load profile", str(APP_DIR), "JSON files (*.json)")
        if not p:
            return
        try:
            spec = json.loads(Path(p).read_text(encoding='utf-8'))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load: {e}")
            return
        # ask for name
        name, ok = QtWidgets.QInputDialog.getText(self, "Profile name", "Enter VM name for loaded profile:")
        if not ok or not name.strip():
            return
        name = name.strip()
        self.manager.add_vm(name, spec)
        self.refresh_vm_list()
        QtWidgets.QMessageBox.information(self, "Loaded", f"Profile loaded as VM: {name}")

    def on_save_snapshot(self):
        it = self.vm_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "Error", "Select VM")
            return
        name = it.text()
        spec = self.manager.vms.get(name,{})
        base = spec.get('hdd_path','')
        if not base:
            QtWidgets.QMessageBox.critical(self, "Error", "No HDD path set for VM")
            return
        qimg = self.manager.config.get('qemu_img') or find_qemu_img()
        if not qimg:
            QtWidgets.QMessageBox.critical(self, "Error", "qemu-img not found")
            return
        snap = self.edit_snap_name.text().strip() or "snap"
        new = str(Path(base).with_name(Path(base).stem + f".{snap}" + Path(base).suffix))
        args = [qimg, 'create', '-f', 'qcow2', '-b', base, new]
        self.append_console("Run: " + " ".join(args))
        try:
            r = subprocess.run(args, capture_output=True, text=True)
            self.append_console(r.stdout or r.stderr)
            if r.returncode == 0:
                QtWidgets.QMessageBox.information(self, "Done", f"Snapshot created: {new}")
            else:
                QtWidgets.QMessageBox.critical(self, "Error", r.stderr or r.stdout)
        except Exception as e:
            self.append_console(str(e))
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

# ------------------ Main entry ------------------
def main():
    manager = VMManager()
    # optional auto elevation
    if os.name == 'nt' and manager.config.get('auto_elevate', False) and not is_admin():
        # try to elevate
        ok = run_as_admin()
        if ok:
            # elevated process started; exit this one
            sys.exit(0)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("QEMU GUI Full")
    window = QemuGUIApp(manager)
    # apply saved theme and language
    window.apply_theme(manager.config.get('theme','light'))
    window.set_language(manager.config.get('lang','ru'))
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
