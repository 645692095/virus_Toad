import frozen  # Pyinstaller多进程代码打包exe出现多个进程解决方案
import multiprocessing
import subprocess, time, sys, os
import win32con
import win32api

CMD = r"WinCoreManagement.exe"  # 需要执行程序的绝对路径


def run(cmd):
    # print('start OK!')
    #os.path.abspath(__file__)：获取当前文件的绝对路径
    #os.path.dirname（）：获取路径名
    #os.chdir（xxx）切换到xxx文件中
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    #在当前文件夹下运行cmd程序（不显示shell窗口，shell=False）
    p = subprocess.Popen(cmd, shell=False)
    p.wait() # 类似于p.join() ，等待上述cmd正常运行以后再往下执行
    try:
        #将cmd这个进程杀死，start /b是指在杀死这个进程之后再在后台重新运行cmd这个程序
        subprocess.call('start /b taskkill /F /IM %s' % cmd) # 清理残余
    except Exception as e:
        # print(e)
        pass

    # print('子进程关闭，重启')
    #递归调用run()，无限重启这个进程
    run(cmd)


if __name__ == '__main__':
    #multiprocessing在window上运行会有Bug：
    # 在使用subprocess时候会启动两个子进程（实际上只需要一个）
    # 解决办法：使用freeze_support（）接口可以解决这个Bug
    multiprocessing.freeze_support()  # Pyinstaller多进程代码打包exe出现多个进程解决方案

    run(CMD)
