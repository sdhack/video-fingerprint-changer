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
    def __init__(self):
        super().__init__()
        self.title('视频指纹修改器 · 批量去重工具')
        self.geometry('780x560')
        self.minsize(680, 480)
        self.update_idletasks()
        w, h = 780, 560
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}')
        self.files = []          # 待处理视频
        self.work_dir = None
        self.cancel = False
        self._log_path = None
        self._build_ui()
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._on_drop)
            self._log('已启用拖拽:直接把视频/文件夹拖进窗口即可')
        else:
            self._log('提示:未安装 tkinterdnd2,拖拽不可用(可用 pip install tkinterdnd2 开启)')

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {'padx': 8, 'pady': 4}

        top = ttk.LabelFrame(self, text=' 1. 添加视频(可直接拖入窗口)')
        top.pack(fill='x', **pad)
        btns = ttk.Frame(top)
        btns.pack(fill='x', **pad)
        ttk.Button(btns, text='添加视频文件', command=self.add_files).pack(side='left', padx=3)
        ttk.Button(btns, text='添加文件夹', command=self.add_folder).pack(side='left', padx=3)
        ttk.Button(btns, text='清空列表', command=self.clear_list).pack(side='left', padx=3)
        ttk.Button(btns, text='打开输出目录', command=self.open_outdir).pack(side='right', padx=3)

        self.listbox = tk.Listbox(top, height=8, selectmode='extended')
        self.listbox.pack(fill='both', expand=True, **pad)
        self.count_var = tk.StringVar(value='共 0 个文件')
        ttk.Label(top, textvariable=self.count_var).pack(anchor='e', padx=8)

        opt = ttk.LabelFrame(self, text=' 2. 输出设置')
        opt.pack(fill='x', **pad)
        row = ttk.Frame(opt)
        row.pack(fill='x', **pad)
        ttk.Label(row, text='输出目录:').pack(side='left')
        self.out_var = tk.StringVar(value='')
        ttk.Entry(row, textvariable=self.out_var).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(row, text='浏览...', command=self.choose_outdir).pack(side='left')

        row2 = ttk.Frame(opt)
        row2.pack(fill='x', **pad)
        ttk.Label(row2, text='每个视频生成份数:').pack(side='left')
        self.copies_var = tk.IntVar(value=1)
        spin = ttk.Spinbox(row2, from_=1, to=100, width=5, textvariable=self.copies_var)
        spin.pack(side='left', padx=4)
        ttk.Label(row2, text='(大于 1 时每份均为不同指纹的新副本)').pack(side='left')
        self.thread_var = tk.IntVar(value=max(1, min(8, os.cpu_count() or 4)))
        ttk.Label(row2, text='   并发线程:').pack(side='left')
        ttk.Spinbox(row2, from_=1, to=32, width=4, textvariable=self.thread_var).pack(side='left', padx=4)

        row3 = ttk.Frame(opt)
        row3.pack(fill='x', **pad)
        self.append_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row3, variable=self.append_var,
            text='兜底:找不到空闲区时在文件尾部附加随机数据(文件会略微增大,保证一定能输出)').pack(side='left')

        go = ttk.Frame(self)
        go.pack(fill='x', **pad)
        self.start_btn = ttk.Button(go, text=' 3. 开始处理 ▶', command=self.start)
        self.start_btn.pack(side='left', padx=3)
        self.stop_btn = ttk.Button(go, text='停止', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=3)
        self.progress = ttk.Progressbar(go, mode='determinate')
        self.progress.pack(side='left', fill='x', expand=True, padx=8)

        logf = ttk.LabelFrame(self, text=' 运行日志 ')
        logf.pack(fill='both', expand=True, **pad)
        self.log_text = tk.Text(logf, height=8, state='disabled', font=('Consolas', 9))
        self.log_text.pack(fill='both', expand=True, padx=4, pady=4)

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
