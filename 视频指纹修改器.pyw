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
    # ---------------- 配色(Instagram 极简风) ----------------
    C_BG      = '#fafafa'
    C_CARD    = '#ffffff'
    C_BORDER  = '#dbdbdb'
    C_TEXT    = '#262626'
    C_MUTED   = '#8e8e8e'
    C_ACCENT  = '#d62976'   # INS 玫红(选中/计数)
    C_LOG_BG  = '#0f1116'
    C_LOG_FG  = '#b9c3d4'
    GRAD      = ('#7b2ff7', '#d62976', '#f77737', '#fcaf45')  # INS 渐变
    FONT      = ('微软雅黑', 9)
    FONT_B    = ('微软雅黑', 10, 'bold')
    FONT_MONO = ('Consolas', 9)

    @staticmethod
    def _hex2rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    def _draw_gradient(self, canvas):
        w = canvas.winfo_width() or 1
        h = canvas.winfo_height() or 1
        canvas.delete('grad')
        cs = [self._hex2rgb(c) for c in self.GRAD]
        for x in range(w):
            t = x / max(w - 1, 1)
            seg = min(int(t * (len(cs) - 1)), len(cs) - 2)
            tt = t * (len(cs) - 1) - seg
            c = '#%02x%02x%02x' % tuple(int(a + (b - a) * tt) for a, b in zip(cs[seg], cs[seg + 1]))
            canvas.create_line(x, 0, x + 1, h, fill=c, tags='grad')
        canvas.tag_lower('grad')

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        self.configure(bg=self.C_BG)
        style.configure('.', background=self.C_BG, font=self.FONT, focuscolor=self.C_ACCENT)
        style.configure('TEntry', fieldbackground='#ffffff', foreground=self.C_TEXT,
                        bordercolor=self.C_BORDER, lightcolor=self.C_BORDER,
                        darkcolor=self.C_BORDER, insertcolor=self.C_ACCENT, padding=6)
        style.map('TEntry', bordercolor=[('focus', self.C_ACCENT)],
                  lightcolor=[('focus', self.C_ACCENT)], darkcolor=[('focus', self.C_ACCENT)])
        style.configure('TSpinbox', fieldbackground='#ffffff', foreground=self.C_TEXT,
                        bordercolor=self.C_BORDER, lightcolor=self.C_BORDER,
                        darkcolor=self.C_BORDER, arrowsize=11, padding=3)
        style.configure('TCheckbutton', background=self.C_BG, foreground=self.C_TEXT)
        style.map('TCheckbutton', background=[('active', self.C_BG)])
        style.configure('IG.Horizontal.TProgressbar', background=self.C_ACCENT,
                        troughcolor='#f0f0f0', bordercolor=self.C_BG,
                        lightcolor=self.C_ACCENT, darkcolor=self.C_ACCENT, thickness=6)

    # ---------------- 药丸按钮 ----------------
    class PillButton(tk.Canvas):
        """圆角药丸按钮(真正的 Canvas 子类,支持 ['state'] 与 configure(state=))。
        kind: primary=黑底白字 / ghost=白底描边 / danger=红底白字"""

        SPECS = {'primary': ('#262626', '#ffffff', '#3d3d3d', None, 'FONT_B'),
                 'ghost':   ('#ffffff', '#262626', '#f2f2f2', '#dbdbdb', 'FONT'),
                 'danger':  ('#ed4956', '#ffffff', '#d63139', None, 'FONT')}

        def __init__(self, app, parent, text, command, kind='ghost'):
            self._app = app
            self._cmd = command
            self._text = text
            self._spec = self.SPECS[kind]
            self._disabled = False
            import tkinter.font as tkfont
            self._font = tkfont.Font(font=getattr(app, self._spec[4]))
            w = self._font.measure(text) + (44 if kind == 'primary' else 26)
            h = self._font.metrics('linespace') + (18 if kind == 'primary' else 12)
            super().__init__(parent, width=w, height=h, bg=parent['bg'],
                             highlightthickness=0, cursor='hand2')

        # -- 绘制 --
        def _rrect(self, x1, y1, x2, y2, r, **kw):
            pts = [x1+r,y1, x2-r,y1, x2,y1, x2,y1+r, x2,y2-r, x2,y2,
                   x2-r,y2, x1+r,y2, x1,y2, x1,y2-r, x1,y1+r, x1,y1]
            return self.create_polygon(pts, smooth=True, **kw)

        def _colors(self):
            bg, fg, hover, outline, _ = self._spec
            if self._disabled:
                return '#f1f1f1', '#b8b8b8', '#f1f1f1'
            return bg, fg, outline or bg

        def paint(self):
            bg, fg, ol = self._colors()
            w, h = int(self['width']), int(self['height'])
            self.delete('all')
            self._rrect(1, 1, w - 1, h - 1, h // 2, fill=bg, outline=ol)
            self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

        def _hover(self, _e=None):
            if not self._disabled:
                bg, fg, hover, outline, _ = self._spec
                w, h = int(self['width']), int(self['height'])
                self.delete('all')
                self._rrect(1, 1, w - 1, h - 1, h // 2, fill=hover, outline=hover)
                self.create_text(w / 2, h / 2, text=self._text, fill=fg, font=self._font)

        def _leave(self, _e=None):
            self.paint()

        def _click(self, _e=None):
            if not self._disabled:
                self._cmd()

        # -- 状态接口 --
        def __getitem__(self, key):
            if key == 'state':
                return 'disabled' if self._disabled else 'normal'
            return super().__getitem__(key)

        def configure(self, cnf=None, **kw):
            if cnf and isinstance(cnf, str):
                kw[cnf] = None
                cnf = None
            if 'state' in kw:
                self._disabled = kw.pop('state') == 'disabled'
                self.paint()
                super().configure(cursor='arrow' if self._disabled else 'hand2')
            return super().configure(cnf, **kw) if (cnf or kw) else None

    def _pill(self, parent, text, command, kind='ghost'):
        btn = self.PillButton(self, parent, text, command, kind)
        btn.bind('<Button-1>', btn._click)
        btn.bind('<Enter>', btn._hover)
        btn.bind('<Leave>', btn._leave)
        btn.paint()
        return btn

    # ---------------- 卡片 ----------------
    def _card(self, parent, title, note=''):
        card = tk.Frame(parent, bg=self.C_CARD,
                        highlightbackground=self.C_BORDER, highlightthickness=1)
        head = tk.Frame(card, bg=self.C_CARD)
        head.pack(fill='x', padx=18, pady=(16, 8))
        tk.Label(head, text=title, bg=self.C_CARD, fg=self.C_TEXT,
                 font=('微软雅黑', 11, 'bold')).pack(side='left')
        if note:
            tk.Label(head, text=note, bg=self.C_CARD, fg=self.C_MUTED,
                     font=self.FONT).pack(side='left', padx=10)
        return card, head

    def __init__(self):
        super().__init__()
        self.withdraw()  # 先隐藏窗口,居中定位完成后再显示,避免启动时位置跳动
        self.title('视频指纹修改器')
        self.minsize(680, 500)
        self.files = []          # 待处理视频
        self.work_dir = None
        self.cancel = False
        self._log_path = None
        self._setup_style()
        self._build_ui()
        self.update_idletasks()
        w, h = 820, 620
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
        # INS 渐变横幅
        banner = tk.Canvas(self, height=96, bg=self.GRAD[0], highlightthickness=0)
        banner.pack(fill='x')
        banner.bind('<Configure>', lambda e: self._draw_gradient(banner))
        banner.create_text(28, 36, text='视频指纹修改器', fill='white',
                           font=('微软雅黑', 17, 'bold'), anchor='w')
        banner.create_text(28, 66, text='大小不变 · 画质零损失 · 批量生成新指纹',
                           fill='#ffe3f1', font=('微软雅黑', 9), anchor='w')
        banner.create_text(792, 48, text='v1.1', fill='#ffffff',
                           font=('微软雅黑', 9, 'bold'), anchor='e')

        wrap = tk.Frame(self, bg=self.C_BG)
        wrap.pack(fill='both', expand=True, padx=24)

        # 视频列表
        card1, head1 = self._card(wrap, '视频列表', '将文件或文件夹拖入窗口即可添加')
        card1.pack(fill='both', expand=True, pady=(16, 14))
        self.count_var = tk.StringVar(value='0 个文件')
        tk.Label(head1, textvariable=self.count_var, bg=self.C_CARD, fg=self.C_ACCENT,
                 font=('微软雅黑', 9, 'bold')).pack(side='right')
        btns = tk.Frame(card1, bg=self.C_CARD)
        btns.pack(fill='x', padx=18)
        self._pill(btns, '添加视频', self.add_files, 'primary').pack(side='left')
        self._pill(btns, '添加文件夹', self.add_folder).pack(side='left', padx=8)
        self._pill(btns, '清空', self.clear_list).pack(side='left')
        self._pill(btns, '打开输出目录', self.open_outdir).pack(side='right')

        self.listbox = tk.Listbox(card1, height=7, selectmode='extended', bd=0,
                                  bg='#ffffff', fg=self.C_TEXT, font=self.FONT,
                                  selectbackground='#fbe9f1', selectforeground=self.C_TEXT,
                                  activestyle='none', highlightthickness=0)
        self.listbox.pack(fill='both', expand=True, padx=18, pady=(10, 16))

        # 输出设置
        card2, _ = self._card(wrap, '输出设置')
        card2.pack(fill='x', pady=(0, 14))
        grid = tk.Frame(card2, bg=self.C_CARD)
        grid.pack(fill='x', padx=18, pady=(2, 4))
        grid.columnconfigure(1, weight=1)
        tk.Label(grid, text='输出目录', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).grid(row=0, column=0, sticky='w', pady=4)
        self.out_var = tk.StringVar(value='')
        ttk.Entry(grid, textvariable=self.out_var).grid(
            row=0, column=1, sticky='ew', padx=12, pady=4)
        self._pill(grid, '浏览', self.choose_outdir).grid(row=0, column=2, pady=4)

        tk.Label(grid, text='生成份数', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).grid(row=1, column=0, sticky='w', pady=4)
        sub = tk.Frame(grid, bg=self.C_CARD)
        sub.grid(row=1, column=1, sticky='w', padx=12, pady=4)
        self.copies_var = tk.IntVar(value=1)
        ttk.Spinbox(sub, from_=1, to=100, width=5, textvariable=self.copies_var,
                    font=self.FONT).pack(side='left')
        tk.Label(sub, text='每份均为不同指纹的新副本', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).pack(side='left', padx=10)
        tk.Label(sub, text='并发线程', bg=self.C_CARD, fg=self.C_MUTED,
                 font=self.FONT).pack(side='left', padx=(24, 6))
        self.thread_var = tk.IntVar(value=max(1, min(8, os.cpu_count() or 4)))
        ttk.Spinbox(sub, from_=1, to=32, width=4, textvariable=self.thread_var,
                    font=self.FONT).pack(side='left')

        self.append_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grid, variable=self.append_var,
                        text='兜底:找不到空闲区时在尾部附加随机数据(略微增大文件,保证输出)'
                        ).grid(row=2, column=0, columnspan=3, sticky='w', pady=(2, 12))

        # 执行区
        go = tk.Frame(wrap, bg=self.C_BG)
        go.pack(fill='x', pady=(0, 14))
        self.start_btn = self._pill(go, '开始处理  ▶', self.start, 'primary')
        self.start_btn.pack(side='left')
        self.stop_btn = self._pill(go, '停止', self.stop, 'danger')
        self.stop_btn.configure(state='disabled')
        self.stop_btn.pack(side='left', padx=10)
        self.progress = ttk.Progressbar(go, mode='determinate',
                                        style='IG.Horizontal.TProgressbar')
        self.progress.pack(side='left', fill='x', expand=True, padx=(10, 0))

        # 日志区(极简暗色)
        logcard = tk.Frame(wrap, bg=self.C_LOG_BG)
        logcard.pack(fill='both', expand=True, pady=(0, 20))
        self.log_text = tk.Text(logcard, height=6, state='disabled', bd=0,
                                bg=self.C_LOG_BG, fg=self.C_LOG_FG,
                                insertbackground=self.C_LOG_FG, font=self.FONT_MONO,
                                highlightthickness=0, padx=16, pady=10)
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
