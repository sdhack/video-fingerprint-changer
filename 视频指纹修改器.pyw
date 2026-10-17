# -*- coding: utf-8 -*-
"""视频指纹修改器 - Windows 小工具

拖入视频文件(或文件夹),在保持文件大小与画质完全不变的情况下,
修改文件指纹(MD5),让平台(如千川广告后台)识别为新视频。
支持批量处理、每个视频一键生成多份不同指纹的副本。
"""
import os
import sys
import shutil
import threading
import queue
import traceback
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor

import fingerprint

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except ImportError:
    BaseTk = tk.Tk
    HAS_DND = False


class App(BaseTk):
    # ---------------- 配色与样式 ----------------
    C_BG      = '#eef1f6'   # 窗口背景
    C_CARD    = '#ffffff'   # 卡片背景
    C_BORDER  = '#e2e6ee'   # 卡片描边
    C_ACCENT  = '#2f6bed'   # 品牌蓝
    C_ACCENT_D= '#1e56d6'   # 悬停深蓝
    C_TEXT    = '#1f2430'   # 主文字
    C_MUTED   = '#69707f'   # 次要文字
    C_DANGER  = '#e5484d'   # 停止按钮
    C_LOG_BG  = '#151821'   # 日志区背景
    C_LOG_FG  = '#c8d1e0'   # 日志区文字

    FONT      = ('微软雅黑', 9)
    FONT_B    = ('微软雅黑', 10, 'bold')
    FONT_MONO = ('Consolas', 9)

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        self.configure(bg=self.C_BG)

        style.configure('.', background=self.C_BG, font=self.FONT)
        style.configure('Card.TFrame', background=self.C_CARD)
        style.configure('Card.TLabel', background=self.C_CARD, foreground=self.C_TEXT)
        style.configure('Muted.TLabel', background=self.C_CARD, foreground=self.C_MUTED)
        style.configure('Card.TLabelframe', background=self.C_CARD,
                        bordercolor=self.C_BORDER, relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe.Label', background=self.C_CARD,
                        foreground=self.C_TEXT, font=self.FONT_B)
        style.configure('TEntry', fieldbackground='#fbfcfe', bordercolor=self.C_BORDER,
                        lightcolor=self.C_BORDER, darkcolor=self.C_BORDER, padding=3)
        style.configure('TSpinbox', fieldbackground='#fbfcfe', bordercolor=self.C_BORDER,
                        lightcolor=self.C_BORDER, darkcolor=self.C_BORDER, padding=2)
        style.configure('Card.TCheckbutton', background=self.C_CARD, foreground=self.C_TEXT)
        style.map('Card.TCheckbutton', background=[('active', self.C_CARD)])

        # 主按钮:品牌蓝 + 悬停加深 + 按下更深
        style.configure('Accent.TButton', background=self.C_ACCENT, foreground='white',
                        font=self.FONT_B, borderwidth=0, focusthickness=0, padding=(18, 8))
        style.map('Accent.TButton',
                  background=[('disabled', '#a9bdef'), ('pressed', self.C_ACCENT_D),
                              ('active', self.C_ACCENT_D)],
                  foreground=[('disabled', '#eef2ff')])
        # 次要按钮:白底描边 + 悬停浅蓝
        style.configure('Ghost.TButton', background=self.C_CARD, foreground=self.C_TEXT,
                        bordercolor=self.C_BORDER, borderwidth=1, focusthickness=0,
                        padding=(10, 5))
        style.map('Ghost.TButton',
                  background=[('disabled', '#f4f5f7'), ('active', '#eef3ff')],
                  foreground=[('disabled', '#9aa1ad')])
        # 危险按钮(停止)
        style.configure('Danger.TButton', background=self.C_DANGER, foreground='white',
                        font=self.FONT_B, borderwidth=0, focusthickness=0, padding=(14, 8))
        style.map('Danger.TButton',
                  background=[('disabled', '#f3b7b9'), ('active', '#c93a3f')])

        style.configure('Accent.Horizontal.TProgressbar', background=self.C_ACCENT,
                        troughcolor='#e4e8f0', bordercolor=self.C_BG, lightcolor=self.C_ACCENT,
                        darkcolor=self.C_ACCENT, thickness=10)

    def _card(self, parent, title):
        """白色卡片容器,带彩色编号徽章标题。"""
        card = ttk.Frame(parent, style='Card.TLabelframe', borderwidth=1)
        head = tk.Frame(card, bg=self.C_CARD)
        head.pack(fill='x', padx=12, pady=(10, 2))
        badge = tk.Label(head, text=title[0], bg=self.C_ACCENT, fg='white',
                         font=('微软雅黑', 9, 'bold'), width=2, relief='flat')
        badge.pack(side='left')
        tk.Label(head, text=title[2:].strip(), bg=self.C_CARD, fg=self.C_TEXT,
                 font=self.FONT_B).pack(side='left', padx=8)
        return card, head

    def __init__(self):
        super().__init__()
        self.withdraw()  # 先隐藏窗口,居中定位完成后再显示,避免启动时位置跳动
        self.title('视频指纹修改器 · 批量去重工具')
        self.minsize(680, 480)
        self.files = []          # 待处理视频
        self.work_dir = None
        self.cancel = False
        self._log_path = None
        self._setup_style()
        self._build_ui()
        self.update_idletasks()
        w, h = 800, 600
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}')
        self.deiconify()
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._on_drop)
            self._log('已启用拖拽:直接把视频/文件夹拖进窗口即可')
        else:
            self._log('提示:未安装 tkinterdnd2,拖拽不可用(可用 pip install tkinterdnd2 开启)')

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {'padx': 12, 'pady': (6, 0)}

        # 顶部品牌横幅
        banner = tk.Frame(self, bg=self.C_ACCENT)
        banner.pack(fill='x')
        inner = tk.Frame(banner, bg=self.C_ACCENT)
        inner.pack(fill='x', padx=16, pady=12)
        tk.Label(inner, text='🎬 视频指纹修改器', bg=self.C_ACCENT, fg='white',
                 font=('微软雅黑', 15, 'bold')).pack(side='left')
        tk.Label(inner, text='大小不变 · 画质零损失 · 批量生成新指纹',
                 bg=self.C_ACCENT, fg='#cfe0ff',
                 font=('微软雅黑', 9)).pack(side='left', padx=14, pady=(4, 0))
        tk.Label(inner, text='v1.1', bg='#1e56d6', fg='white',
                 font=('微软雅黑', 8, 'bold'), padx=6, pady=2).pack(side='right', pady=(2, 0))

        # 1. 视频列表卡片
        card1, head1 = self._card(self, '1  添加视频(可直接拖入窗口)')
        card1.pack(fill='both', expand=True, **pad)
        self.count_var = tk.StringVar(value='共 0 个文件')
        tk.Label(head1, textvariable=self.count_var, bg=self.C_CARD, fg=self.C_ACCENT,
                 font=('微软雅黑', 9, 'bold')).pack(side='right')
        btns = tk.Frame(card1, bg=self.C_CARD)
        btns.pack(fill='x', padx=12)
        ttk.Button(btns, text='➕ 添加视频', style='Accent.TButton',
                   command=self.add_files).pack(side='left', padx=(0, 8))
        ttk.Button(btns, text='📁 添加文件夹', style='Ghost.TButton',
                   command=self.add_folder).pack(side='left', padx=(0, 8))
        ttk.Button(btns, text='清空列表', style='Ghost.TButton',
                   command=self.clear_list).pack(side='left')
        ttk.Button(btns, text='打开输出目录', style='Ghost.TButton',
                   command=self.open_outdir).pack(side='right')

        list_wrap = tk.Frame(card1, bg=self.C_BORDER)
        list_wrap.pack(fill='both', expand=True, padx=12, pady=(8, 4))
        self.listbox = tk.Listbox(list_wrap, height=7, selectmode='extended', bd=0,
                                  bg='#fbfcfe', fg=self.C_TEXT, font=self.FONT,
                                  selectbackground=self.C_ACCENT, selectforeground='white',
                                  activestyle='none', highlightthickness=0)
        self.listbox.pack(fill='both', expand=True, padx=1, pady=1)

        # 2. 输出设置卡片
        card2, _ = self._card(self, '2  输出设置')
        card2.pack(fill='x', **pad)
        row = tk.Frame(card2, bg=self.C_CARD)
        row.pack(fill='x', padx=12, pady=(6, 2))
        tk.Label(row, text='输出目录', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).pack(side='left')
        self.out_var = tk.StringVar(value='')
        ttk.Entry(row, textvariable=self.out_var, style='TEntry').pack(
            side='left', fill='x', expand=True, padx=8)
        ttk.Button(row, text='浏览...', style='Ghost.TButton',
                   command=self.choose_outdir).pack(side='left')

        row2 = tk.Frame(card2, bg=self.C_CARD)
        row2.pack(fill='x', padx=12, pady=2)
        tk.Label(row2, text='每个视频生成份数', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).pack(side='left')
        self.copies_var = tk.IntVar(value=1)
        ttk.Spinbox(row2, from_=1, to=100, width=5, textvariable=self.copies_var,
                    font=self.FONT).pack(side='left', padx=(6, 4))
        tk.Label(row2, text='份(大于 1 时每份均为不同指纹的新副本)', bg=self.C_CARD,
                 fg=self.C_MUTED, font=self.FONT).pack(side='left')
        tk.Label(row2, text='并发线程', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).pack(side='left', padx=(18, 0))
        self.thread_var = tk.IntVar(value=max(1, min(8, os.cpu_count() or 4)))
        ttk.Spinbox(row2, from_=1, to=32, width=4, textvariable=self.thread_var,
                    font=self.FONT).pack(side='left', padx=6)

        row3 = tk.Frame(card2, bg=self.C_CARD)
        row3.pack(fill='x', padx=12, pady=(2, 8))
        self.append_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row3, style='Card.TCheckbutton', variable=self.append_var,
                        text='兜底:找不到空闲区时在文件尾部附加随机数据(文件会略微增大,保证一定能输出)'
                        ).pack(side='left')

        # 3. 执行区
        go = tk.Frame(self, bg=self.C_BG)
        go.pack(fill='x', padx=12, pady=8)
        self.start_btn = ttk.Button(go, text='▶  开始处理', style='Accent.TButton',
                                    command=self.start)
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(go, text='停止', style='Danger.TButton',
                                   command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=8)
        self.progress = ttk.Progressbar(go, mode='determinate',
                                        style='Accent.Horizontal.TProgressbar')
        self.progress.pack(side='left', fill='x', expand=True, padx=(8, 0))

        # 日志区(控制台风格)
        log_wrap = tk.Frame(self, bg=self.C_LOG_BG)
        log_wrap.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.log_text = tk.Text(log_wrap, height=7, state='disabled', bd=0,
                                bg=self.C_LOG_BG, fg=self.C_LOG_FG,
                                insertbackground=self.C_LOG_FG,
                                font=self.FONT_MONO, highlightthickness=0,
                                padx=10, pady=8)
        self.log_text.pack(fill='both', expand=True)

    # ---------------- 列表 / 拖拽 ----------------
    def _on_drop(self, event):
        raw = self.tk.splitlist(event.data)
        self._add_paths(raw)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title='选择视频文件',
            filetypes=[('视频文件', '*.mp4 *.mov *.m4v *.avi *.flv *.ts *.mkv'), ('所有文件', '*.*')])
        self._add_paths(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title='选择文件夹(将递归扫描视频)')
        if d:
            self._add_paths([d])

    def _add_paths(self, paths):
        added = 0
        for p in paths:
            p = p.strip('{}') if isinstance(p, str) else p
            if os.path.isdir(p):
                for root, _, names in os.walk(p):
                    for n in names:
                        if os.path.splitext(n)[1].lower() in fingerprint.VIDEO_EXTS:
                            self._append_file(os.path.join(root, n))
                            added += 1
            elif os.path.isfile(p):
                self._append_file(p)
                added += 1
        self._refresh_count()
        if added:
            self._log(f'已添加 {added} 个文件')

    def _append_file(self, path):
        if path not in self.files:
            self.files.append(path)
            self.listbox.insert('end', path)

    def clear_list(self):
        self.files.clear()
        self.listbox.delete(0, 'end')
        self._refresh_count()

    def _refresh_count(self):
        self.count_var.set(f'共 {len(self.files)} 个文件')

    # ---------------- 输出目录 ----------------
    def choose_outdir(self):
        d = filedialog.askdirectory(title='选择输出目录')
        if d:
            self.out_var.set(d)

    def open_outdir(self):
        d = self.out_var.get().strip()
        if d and os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showinfo('提示', '输出目录尚未生成,请先处理一次。')

    # ---------------- 处理 ----------------
    def _log(self, msg):
        line = f'[{datetime.datetime.now():%H:%M:%S}] {msg}'
        self.log_text.configure(state='normal')
        self.log_text.insert('end', line + '\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
        try:
            if self._log_path:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
        except Exception:
            pass

    def stop(self):
        self.cancel = True
        self._log('正在停止...')

    def start(self):
        if not self.files:
            messagebox.showwarning('提示', '请先添加视频文件')
            return
        out = self.out_var.get().strip()
        if not out:
            out = os.path.join(os.path.dirname(self.files[0]), '指纹修改输出')
            self.out_var.set(out)
        os.makedirs(out, exist_ok=True)
        try:
            copies = max(1, int(self.copies_var.get()))
            threads = max(1, int(self.thread_var.get()))
        except Exception:
            messagebox.showerror('错误', '份数/线程数设置无效')
            return

        self.cancel = False
        self._log_path = os.path.join(out, '处理日志.txt')
        self._log(f'—— 开始处理:共 {len(self.files)} 个视频 × {copies} 份 ——')
        self.start_btn.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        total = len(self.files) * copies
        self.progress.configure(maximum=total, value=0)
        q = queue.Queue()
        allow_append = bool(self.append_var.get())
        threading.Thread(target=self._worker, args=(out, copies, threads, q, allow_append), daemon=True).start()
        self.after(100, lambda: self._poll(total, q))

    def _worker(self, out, copies, threads, q, allow_append):
        ok = fail = 0

        def one(src):
            nonlocal ok, fail
            if self.cancel:
                return
            base = os.path.splitext(os.path.basename(src))[0]
            ext = os.path.splitext(src)[1] or '.mp4'
            tmp = os.path.join(out, f'__tmp_{os.getpid()}_{abs(hash(src))%99999}{ext}')

            def final_name(crc6):
                dst = os.path.join(out, f'{base}_{crc6}{ext}')
                k = 1
                while os.path.exists(dst):
                    dst = os.path.join(out, f'{base}_{crc6}_{k}{ext}')
                    k += 1
                return dst

            try:
                if copies == 1:
                    crc6 = fingerprint.make_fingerprint(src, tmp, allow_append=allow_append)
                    dst = final_name(crc6)
                    os.rename(tmp, dst)
                    ok += 1
                    q.put(('ok', f'✔ {os.path.basename(src)} → {os.path.basename(dst)}'))
                else:
                    for i in range(1, copies + 1):
                        if self.cancel:
                            return
                        crc6 = fingerprint.make_fingerprint(src, tmp, allow_append=allow_append)
                        dst = final_name(crc6)
                        os.rename(tmp, dst)
                        ok += 1
                        q.put(('ok', f'✔ {os.path.basename(src)} → {os.path.basename(dst)}'))
            except Exception as e:
                fail += 1
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass
                q.put(('err', f'✘ {os.path.basename(src)}: {e}\n{traceback.format_exc()}'))

        with ThreadPoolExecutor(max_workers=threads) as ex:
            list(ex.map(one, list(self.files)))
        q.put(('done', (ok, fail)))

    def _poll(self, total, q):
        done = False
        while not q.empty():
            kind, msg = q.get_nowait()
            if kind == 'done':
                done = True
                summary = msg
            else:
                self._log(msg)
                self.progress.step(1)
        if done:
            ok, fail = summary if summary else (0, 0)
            self.start_btn.configure(state='normal')
            self.stop_btn.configure(state='disabled')
            tail = '已停止' if self.cancel else '全部处理完成'
            self._log(f'—— {tail}:成功 {ok} 个,失败 {fail} 个 ——')
            self._log(f'输出目录:{self.out_var.get().strip()}')
            if messagebox.askyesno(
                    '完成',
                    f'{tail}\n成功 {ok} 个,失败 {fail} 个\n是否打开输出目录?'):
                os.startfile(self.out_var.get().strip())
        else:
            self.after(100, lambda: self._poll(total, q))


def main():
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
