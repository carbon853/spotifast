#!/usr/bin/python3
"""Run only inside local.py's isolated UI sandbox, with synthetic demo data."""
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    phase = sys.argv[1]
    if phase not in ('before', 'after'):
        raise ValueError('expected before or after')
    os.makedirs('/home/build/runtime', mode=0o700, exist_ok=True)
    env = {**os.environ, 'DISPLAY': ':92', 'LIBGL_ALWAYS_SOFTWARE': '1'}
    x = subprocess.Popen(['Xvfb', ':92', '-screen', '0', '1400x1000x24', '-nolisten', 'tcp'], env=env)
    try:
        time.sleep(1)
        for size in ('1280x800', '800x600'):
            for theme in ('light', 'dark'):
                name = f'{phase}-{theme}-{size}'
                out = Path('/evidence') / (name + '.png')
                app = subprocess.Popen(['/target/debug/spotifast', '--demo', '--demo-page', 'liked',
                    '--demo-show', theme, '--demo-data', '/home/build/' + name,
                    '--demo-size', size, '--demo-shot', str(out), '--demo-shot-delay', '8000'], env=env)
                try:
                    deadline = time.monotonic() + 20
                    window = None
                    while time.monotonic() < deadline and app.poll() is None:
                        found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(app.pid)],
                                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
                        if found.returncode == 0 and found.stdout.strip():
                            window = found.stdout.decode().splitlines()[-1]
                            break
                        time.sleep(0.1)
                    if not window:
                        raise RuntimeError('demo window did not appear')
                    subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True, env=env)
                    time.sleep(1)
                    subprocess.run(['xdotool', 'type', '--clearmodifiers', 'a'], check=True, env=env)
                    time.sleep(1)
                    subprocess.run(['xdotool', 'key', 'Next'], check=True, env=env)
                    if app.wait(timeout=30) != 0 or not out.is_file():
                        raise RuntimeError('demo screenshot failed')
                finally:
                    if app.poll() is None:
                        app.terminate(); app.wait(timeout=10)
    finally:
        x.terminate(); x.wait(timeout=10)


if __name__ == '__main__':
    main()
