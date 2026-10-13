"""Muse Studio - tạo video / ảnh hàng loạt, nhiều tài khoản, nhiều luồng (không cần API).
Bấm đúp file .pyw để mở.
Cài một lần:  pip install playwright customtkinter pillow
              playwright install chromium
Tùy chọn (để có ảnh xem trước cho video):  pip install opencv-python   (hoặc cài ffmpeg)
"""
import base64, csv, hashlib, json, os, queue, re, shutil, subprocess, sys, threading, time, traceback, unicodedata
VERSION = "1.0"          # TĂNG số này mỗi lần phát hành bản cập nhật (vd 1.1, 1.2...)
# Link tới version.json bạn upload (xem make_update.py). Để trống = tắt tự cập nhật.
# Ví dụ GitHub: https://raw.githubusercontent.com/TEN_BAN/muse-studio/main/version.json
UPDATE_URL = "https://raw.githubusercontent.com/duongcamphong/muse-AI/main/version.json"

def _ver(s): return tuple(int(x) for x in re.findall(r"\d+", str(s))) or (0,)
_UPD_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MuseStudio", "data", "update")
_UPD_FILE = os.path.join(_UPD_DIR, "muse_studio.py")
# Bản cài (.exe) tự nạp mã mới đã tải về nếu mới hơn bản đóng gói sẵn.
if getattr(sys, "frozen", False) and not globals().get("_MUSE_OVERRIDE") and os.path.exists(_UPD_FILE):
    try:
        _src = open(_UPD_FILE, encoding="utf-8").read()
        _m = re.search(r'^VERSION\s*=\s*"([\d.]+)"', _src, re.M)
        if _m and _ver(_m.group(1)) > _ver(VERSION):
            _code = compile(_src, _UPD_FILE, "exec")
            _g = {"__name__": "__main__", "__file__": _UPD_FILE, "_MUSE_OVERRIDE": True}
            try:
                exec(_code, _g)
                os._exit(0)
            except SystemExit:
                os._exit(0)
            except Exception:
                try: os.remove(_UPD_FILE)       # bản cập nhật hỏng -> bỏ, chạy lại bản gốc
                except Exception: pass
        elif _m and _ver(_m.group(1)) <= _ver(VERSION):
            os.remove(_UPD_FILE)                 # bản cài đã mới hơn/bằng -> dọn
    except Exception:
        try: os.remove(_UPD_FILE)
        except Exception: pass
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False
try:
    import cv2
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

# ======================= Đường dẫn & cài đặt =======================
FROZEN = bool(getattr(sys, "frozen", False))      # True khi chạy từ bản cài đặt (.exe)
if FROZEN:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"  # dùng Chromium đã đóng gói kèm trong app
    BASE = os.path.dirname(sys.executable)
    DATA = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MuseStudio", "data")   # thư mục ghi được, không nằm trong Program Files
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    DATA = os.path.join(BASE, "muse_studio_data")
def res_path(name):
    """Đường dẫn tới tệp đi kèm app (logo, icon) - trong bản cài nằm ở thư mục đóng gói."""
    for d in ((getattr(sys, "_MEIPASS", None), BASE) if FROZEN else (BASE,)):
        if d and os.path.exists(os.path.join(d, name)): return os.path.join(d, name)
    return os.path.join(BASE, name)
PROFILES, DEBUG, THUMBS, IGNORE = (os.path.join(DATA, n) for n in ("profiles", "debug", "thumbs", "ignore"))
for _d in (DATA, PROFILES, THUMBS, IGNORE): os.makedirs(_d, exist_ok=True)
CFG_FILE, TASK_FILE, ERR_FILE = (os.path.join(DATA, n) for n in ("settings.json", "tasks.json", "error.log"))
OLD_USERS = os.path.join(BASE, "users")          # thư mục của bản muse_bulk_v3 cũ (để nhập lại đăng nhập)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
DURS_VI = ["5 giây", "10 giây", "15 giây", "20 giây", "30 giây"]
RATIOS_VI = ["9:16 · Dọc", "16:9 · Ngang", "1:1 · Vuông", "3:4 · Dọc", "4:3 · Ngang"]
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
VID_EXT = (".mp4", ".webm", ".mov")
MAX_REFS = 6

DEF = {
    "url": "", "user": "", "out": os.path.join(os.path.expanduser("~"), "Videos", "MuseStudio"),
    "threads": "4", "wait_min": "60", "headless": True, "theme": "Tối", "lang": "Tiếng Việt",
    "dur_video": "10 giây", "ratio_video": "9:16 · Dọc", "ratio_image": "1:1 · Vuông",
    "delay": "5",                 # nghỉ giữa các lần mở việc (giây)
    "ps": "textarea",             # ô nhập prompt (CSS)
    "send": "",                   # nút gửi (trống = Enter)
    "att": "",                    # nút đính kèm ảnh (CSS, tùy chọn)
    "rs": "",                     # vùng chứa kết quả (CSS, tùy chọn)
    "mw": "250",                  # chỉ lấy video/ảnh rộng tối thiểu (px)
    "busy": "Generating",         # chữ báo "đang tạo"
    "mk2": "1500",                # dung lượng video tối thiểu khi bắt qua mạng (KB)
    "nc": "",                     # nút "chat mới" (tùy chọn)
    "pfx_img": "Hãy tạo một bức ảnh: ",
    "pfx_i2v": "Hãy dùng ảnh đính kèm để tạo video: ",
    "spec_video": " (Thời lượng {dur} giây, tỉ lệ khung hình {ratio}.)",
    "spec_image": " (Tỉ lệ khung hình {ratio}.)",
    "dur_click": "", "ratio_click": "",      # chữ trên nút chọn thời lượng / khung hình của Muse (tùy chọn)
}
ST = dict(DEF); ST["accounts"] = []

def load_settings():
    try:
        d = json.load(open(CFG_FILE, encoding="utf-8"))
        for k, v in d.items(): ST[k] = v
    except Exception:
        pass
    if not ST.get("accounts"):   # lần đầu: nhập các "người dùng" của bản cũ (giữ nguyên đăng nhập), hoặc tạo acc1
        accs = []
        if os.path.isdir(OLD_USERS):
            for n in sorted(os.listdir(OLD_USERS)):
                pr = os.path.join(OLD_USERS, n, "browser_profile")
                if os.path.isdir(pr): accs.append({"name": n, "profile": pr, "on": True})
            if accs:
                try:
                    old = json.load(open(os.path.join(OLD_USERS, os.path.basename(os.path.dirname(accs[0]["profile"])), "settings.json"), encoding="utf-8"))
                    for k in ("url", "out", "ps", "send", "att", "rs", "mw", "busy", "mk2", "nc", "pfx_img", "pfx_i2v"):
                        if old.get(k): ST[k] = old[k]
                except Exception:
                    pass
        ST["accounts"] = accs or [{"name": "acc1", "profile": os.path.join(PROFILES, "acc1"), "on": True}]
load_settings()

# ======================= Ngôn ngữ (Tiếng Việt / English) =======================
# Dữ liệu gốc (hàng đợi, thông báo lỗi) luôn lưu bằng tiếng Việt; chỉ dịch ở lúc hiển thị.
import functools
LANG = ST.get("lang", "Tiếng Việt")
CHOICES = {"theme": ["Tối", "Sáng", "Theo hệ thống"], "lang": ["Tiếng Việt", "English"]}
EN = {
"\n\nGợi ý: ": "\n\nHint: ",
"  (xem chi tiết)": "  (see details)",
" (hiện 120 tệp mới nhất)": " (showing the 120 newest)",
"+  Thêm vào hàng đợi": "+  Add to queue",
"0 lỗi": "0 errors",
"1 dòng / prompt": "1 line / prompt",
"Bạn đã bấm Dừng nên việc này bị bỏ dở. Bấm 'Gửi lại' hoặc 'Chạy lại task lỗi' để làm tiếp.": "You pressed Stop, so this job was left unfinished. Click 'Resend' or 'Retry failed tasks' to continue.",
"Bật": "On",
"Bắt đầu chạy {} của '{}': {} tài khoản x {} luồng ({}).": "Started {} run for '{}': {} accounts x {} threads ({}).",
"Bỏ qua ảnh nhỏ như icon": "Skips small images such as icons",
"Chi tiết lỗi - việc {}": "Error details - job {}",
"Chưa cài trình duyệt cho Playwright. Mở Command Prompt, chạy: playwright install chromium": "The Playwright browser is not installed. Open Command Prompt and run: playwright install chromium",
"Chưa có gợi ý riêng cho lỗi này. Xem mục Nhật ký (error.log) và gửi cho người hỗ trợ.": "No specific hint for this error. Check the Log page (error.log) and send it to whoever supports you.",
"Chưa có nhật ký lỗi": "No error log yet",
"Chưa có task nào đang chờ của người dùng này. Hãy thêm prompt vào hàng đợi trước.": "This user has no queued tasks. Add prompts to the queue first.",
"Chưa có task nào.\nNhập prompt ở bên trái rồi bấm “Thêm vào hàng đợi”.": "No tasks yet.\nEnter prompts on the left, then click “Add to queue”.",
"Chưa có thành phẩm nào trong thư mục này.": "No finished files in this folder yet.",
"Chưa có tài khoản nào được bật và đã đăng nhập.\nVào mục Tài khoản, bấm 'Đăng nhập (mở Chrome)' rồi đăng nhập Muse.": "No account is enabled and logged in.\nGo to Accounts, click 'Log in (open Chrome)' and sign in to Muse.",
"Chưa nhập tên người dùng": "No user name entered",
"Chưa đăng nhập": "Not logged in",
"Chạy lại task lỗi": "Retry failed tasks",
"Chạy ngầm": "Run in background",
"Chỉ lấy video/ảnh rộng tối thiểu (px)": "Only take videos/images at least this wide (px)",
"Chỉ lấy {} ảnh đầu tiên.": "Only the first {} images will be used.",
"Chọn Tệp": "Choose files",
"Chọn file prompt": "Choose prompt file",
"Chọn thư mục...": "Choose folder...",
"Chọn tất cả": "Select all",
"Chọn ảnh (ảnh thứ k dùng cho prompt thứ k)": "Choose images (image k is used for prompt k)",
"Chọn ảnh cho prompt #{} (tối đa {})": "Choose images for prompt #{} (max {})",
"Chọn ảnh dùng chung": "Choose shared images",
"Chờ tối đa (phút)": "Max wait (minutes)",
"Chủ đề": "Theme",
"Chứa cài đặt, hồ sơ đăng nhập, ảnh chụp debug và hàng đợi.": "Holds settings, login profiles, debug screenshots and the queue.",
"Chữ báo đang tạo": "\"Generating\" indicator text",
"Chữ trên nút chọn khung hình": "Text on Muse's aspect-ratio button",
"Chữ trên nút chọn thời lượng": "Text on Muse's duration button",
"Chữ đứng trước prompt": "Text placed before the prompt",
"Cài đặt": "Settings",
"Có thể phiên đăng nhập đã hết hạn hoặc Muse hiện trang khác. Vào mục Tài khoản, bấm 'Đăng nhập', đăng nhập lại rồi chạy lại. Xem ảnh chụp trong thư mục debug (mục Nhật ký).": "Your login session may have expired, or Muse is showing a different page. Go to Accounts, click 'Log in', sign in again and rerun. See the screenshot in the debug folder (Log page).",
"Có {} prompt nhưng {} ảnh ghép.\nẢnh được ghép theo thứ tự; prompt nào không có ảnh sẽ chạy không ảnh. Tiếp tục?": "There are {} prompts but {} paired images.\nImages are paired in order; prompts without an image will run without one. Continue?",
"Cần giữ ít nhất một tài khoản.": "At least one account must be kept.",
"Cần khởi động lại": "Restart required",
"Cần khởi động lại Muse Studio để áp dụng chủ đề hoặc ngôn ngữ mới.\nKhởi động lại ngay?": "Muse Studio needs to restart to apply the new theme or language.\nRestart now?",
"Cần xử lý": "Needs attention",
"Cửa sổ trình duyệt bị đóng giữa chừng. Đừng tắt Chrome khi tool đang chạy, rồi bấm 'Gửi lại'.": "The browser window was closed midway. Don't close Chrome while the app is running, then click 'Resend'.",
"Dung lượng video tối thiểu khi bắt qua mạng (KB)": "Minimum video size when captured from the network (KB)",
"Dán link trang có ô nhập prompt. Mỗi việc sẽ mở link này trong một tab mới nên kết quả không bị lẫn nhau.": "Paste the link of the page that has the prompt box. Each job opens this link in a new tab, so results don't get mixed up.",
"Dùng {dur} và {ratio}. Để trống nếu Muse đã có nút chọn riêng.": "Use {dur} and {ratio}. Leave empty if Muse already has its own selector buttons.",
"Dùng {ratio}. Để trống để tắt.": "Use {ratio}. Leave empty to turn off.",
"Dừng tất cả": "Stop all",
"Dữ liệu ứng dụng": "App data",
"Ghép ảnh theo prompt": "Pair images with prompts",
"Giao diện": "Appearance",
"Giao diện Muse": "Muse page",
"Giãn cách khi một tài khoản mở nhiều tab liên tiếp.": "Spacing when one account opens several tabs in a row.",
"Gợi ý: ": "Hint: ",
"Gửi lại": "Resend",
"Gửi tệp này cho người hỗ trợ khi tool gặp lỗi.": "Send this file to whoever supports you when the app hits an error.",
"Hoàn tất": "Done",
"Hoàn tất lượt chạy.": "Run finished.",
"Hàng đợi trống": "Queue is empty",
"Hàng đợi {}": "{} queue",
"Hãy dán link trang Muse ở ô phía trên.": "Paste the Muse page link in the box above.",
"Hãy dừng việc đang chạy trước khi xóa tài khoản.": "Stop the running jobs before deleting an account.",
"Hãy nhập Tên người dùng để video lưu vào thư mục riêng, tránh bị lộn với người khác.": "Enter a user name so files are saved to a separate folder and don't get mixed with other people's.",
"Hãy nhập hoặc nạp file ít nhất một prompt.": "Enter or load at least one prompt.",
"Hủy đã chọn": "Cancel selected",
"Khi có ảnh tham chiếu": "When there are reference images",
"Khi khởi động": "On startup",
"Khi tạo ảnh": "When creating images",
"Kho thành phẩm": "Output library",
"Khung hình": "Aspect ratio",
"Khôi phục cài đặt về mặc định": "Restore settings to defaults",
"Khôi phục mặc định": "Restore defaults",
"Không có lỗi": "No errors",
"Không có task nào bị lỗi.": "No tasks have failed.",
"Không ghi được vào Windows (tính năng này chỉ có trên Windows, hoặc bị chặn quyền).": "Could not write to Windows (this feature is Windows-only, or permission was blocked).",
"Không hiện cửa sổ Chrome khi tool đang làm việc.": "Don't show the Chrome window while the app is working.",
"Không mở được": "Cannot open",
"Không mở được:\n{}": "Cannot open:\n{}",
"Không thực hiện được": "Could not do that",
"Không tìm thấy cài đặt nào khớp với “{}”.\nThử từ khóa khác, ví dụ: ngầm, prompt, nút gửi.": "No settings match “{}”.\nTry another keyword, e.g. background, prompt, send button.",
"Không tệp nào được chọn": "No file selected",
"Không xóa được": "Cannot delete",
"Khởi động lại để áp dụng": "Restart to apply",
"LOẠI": "TYPE",
"Link trang tạo video / ảnh của Muse": "Muse video / image creation page link",
"Link tải bị từ chối (link hết hạn hoặc cần đăng nhập). Đăng nhập lại rồi chạy lại.": "The download link was rejected (expired, or login required). Log in again and rerun.",
"Link tải bị từ chối vì phiên đăng nhập hết hạn. Đăng nhập lại rồi chạy lại.": "The download link was rejected because the login session expired. Log in again and rerun.",
"Link tải không còn tồn tại. Thử gửi lại việc này.": "The download link no longer exists. Try resending this job.",
"Lưu vào: ": "Saves to: ",
"Lọc bớt các tệp video quá nhỏ.": "Filters out video files that are too small.",
"Lỗi": "Error",
"Lỗi mạng hoặc link sai. Kiểm tra Internet và link Muse ở mục Tài khoản.": "Network error or wrong link. Check your Internet and the Muse link on the Accounts page.",
"Lời nhắc (prompt)": "Prompts",
"Muse Studio - Tạo video hàng loạt": "Muse Studio - Bulk video creation",
"Muse chưa trả kết quả theo dạng tool nhận ra được. Mở file jobNNN_info.txt trong thư mục debug để xem Muse đã trả lời gì; có thể Muse đang chậm, hãy thử gửi lại.": "Muse did not return a result in a form the app recognizes. Open jobNNN_info.txt in the debug folder to see what Muse replied; Muse may be slow, so try resending.",
"Muse hiện chữ này khi đang tạo (vd: Generating)": "Muse shows this text while generating (e.g. Generating)",
"Mặc định: textarea": "Default: textarea",
"Mọi người dùng": "All users",
"Mỗi tài khoản có hồ sơ trình duyệt riêng. Đăng nhập một lần; sau đó tool tự chạy (ngầm hoặc hiện cửa sổ, chỉnh ở Cài đặt). Các tài khoản đang bật sẽ chia nhau hàng đợi.": "Each account has its own browser profile. Log in once; after that the app runs by itself (in the background or with a visible window, set in Settings). Enabled accounts share the queue.",
"Một chú mèo phi hành gia trên mặt trăng, phong cách điện ảnh...\nChân dung cô gái dưới ánh hoàng hôn, màu phim...": "An astronaut cat on the moon, cinematic style...\nPortrait of a girl at sunset, film colors...",
"Một con phố Tokyo dưới mưa, ánh đèn neon...\nCảnh biển lúc bình minh, camera tiến chậm...": "A Tokyo street in the rain, neon lights...\nSeaside at dawn, camera slowly pushing in...",
"Mở": "Open",
"Nghỉ giữa các lần mở việc (giây)": "Pause between job launches (seconds)",
"Ngôn ngữ": "Language",
"Nhiều": "Multiple",
"Nhiều dòng / prompt": "Multiple lines / prompt",
"Nhận kết quả": "Receiving results",
"Nhập file": "Import file",
"Nhập prompt": "Enter prompts",
"Nhật ký": "Log",
"Nút 'chat mới' (CSS)": "'New chat' button (CSS)",
"Nút chọn của Muse": "Muse selector buttons",
"Nút gửi (CSS)": "Send button (CSS)",
"Nút đính kèm ảnh (CSS)": "Attach-image button (CSS)",
"Prompt ảnh": "Image prompt",
"Quá nhiều ảnh": "Too many images",
"Sao chép": "Copy",
"Số luồng / tài khoản": "Threads / account",
"Số lượng khác nhau": "Counts differ",
"THAO TÁC": "ACTIONS",
"TIẾN TRÌNH": "PROGRESS",
"Task này có {} ảnh.\n\nCó = chọn ảnh mới thay thế\nKhông = xóa hết ảnh\nHủy = giữ nguyên": "This task has {} images.\n\nYes = choose new images to replace them\nNo = remove all images\nCancel = keep as is",
"Task đang chạy, chưa gán lại ảnh được.": "This task is running; images can't be reassigned yet.",
"Thay thế nội dung hiện tại?\n(Chọn 'Không' để nối thêm vào cuối)": "Replace the current content?\n(Choose 'No' to append at the end)",
"Thiết lập đợt chạy": "Run settings",
"Thiếu link": "Missing link",
"Thiếu prompt": "Missing prompt",
"Thiếu tên người dùng": "Missing user name",
"Thêm tài khoản": "Add account",
"Thông số tự thêm vào prompt": "Parameters added to the prompt",
"Thư mục": "Folder",
"Thư mục dữ liệu": "Data folder",
"Thư mục gốc lưu {}": "Output root folder ({})",
"Thời lượng": "Duration",
"Tiếng Việt hoặc English. Cần khởi động lại app để áp dụng.": "Vietnamese or English. Restart the app to apply.",
"Tool bị đóng khi việc đang chạy. Bấm 'Gửi lại' (lưu ý: có thể Muse đã tạo sẵn video đó).": "The app was closed while the job was running. Click 'Resend' (note: Muse may have already created that video).",
"Tool chưa ghi lỗi nào ra tệp error.log.": "The app hasn't written any errors to error.log yet.",
"Tool không bấm được nút đính kèm ảnh của Muse. Thử đăng nhập lại; nếu vẫn lỗi, nhập CSS nút đính kèm trong Cài đặt hoặc gửi ảnh chụp trong thư mục debug cho người hỗ trợ.": "The app couldn't click Muse's attach-image button. Try logging in again; if it still fails, enter the attach button CSS in Settings or send the screenshot from the debug folder to whoever supports you.",
"Trang tải quá chậm hoặc nút cần bấm không xuất hiện. Kiểm tra mạng và link rồi gửi lại.": "The page loaded too slowly or the button to click didn't appear. Check your network and link, then resend.",
"Trình duyệt tự động": "Automated browser",
"Trùng tên": "Duplicate name",
"Tài khoản": "Accounts",
"Tài khoản Muse": "Muse accounts",
"Tài khoản này đang chạy việc. Hãy dừng trước khi mở Chrome để đăng nhập.": "This account is running jobs. Stop them before opening Chrome to log in.",
"Tên người dùng (mỗi người một thư mục riêng)": "User name (each person gets a separate folder)",
"Tên tài khoản mới (vd: acc2):": "New account name (e.g. acc2):",
"Tìm prompt, tài khoản...": "Search prompts, accounts...",
"Tùy chọn": "Optional",
"Tùy chọn, vd: {dur}s - tool sẽ bấm vào chữ này trước khi gửi": "Optional, e.g. {dur}s - the app clicks this text before sending",
"Tùy chọn, vd: {ratio}": "Optional, e.g. {ratio}",
"Tùy chọn; tool tự dò nếu để trống": "Optional; the app auto-detects if left empty",
"Tạo video": "Create video",
"Tạo {}": "Create {}",
"Tạo ảnh": "Create image",
"Tất cả": "All",
"Tất cả trạng thái": "All statuses",
"Tệp nhật ký lỗi (error.log)": "Error log file (error.log)",
"Tối, Sáng hoặc theo chế độ của Windows. Cần khởi động lại app để áp dụng.": "Dark, Light, or follow Windows. Restart the app to apply.",
"Tổng tác vụ": "Total tasks",
"Tự khởi động cùng Windows": "Start with Windows",
"Tự mở Muse Studio khi bạn đăng nhập máy tính. Nếu sau này di chuyển file .pyw, hãy tắt rồi bật lại mục này.": "Open Muse Studio automatically when you sign in to your computer. If you later move the .pyw file, turn this off and on again.",
"Việc này đã bị hủy theo yêu cầu của bạn.": "This job was cancelled at your request.",
"Vào mục Tài khoản và dán link trang Muse trước.": "Go to Accounts and paste the Muse page link first.",
"Vùng chứa kết quả (CSS)": "Results container (CSS)",
"Văn bản": "Text",
"WORKSPACE     /     CÀI ĐẶT": "WORKSPACE     /     SETTINGS",
"WORKSPACE     /     KHO THÀNH PHẨM": "WORKSPACE     /     OUTPUT LIBRARY",
"WORKSPACE     /     NHẬT KÝ": "WORKSPACE     /     LOG",
"WORKSPACE     /     TÀI KHOẢN": "WORKSPACE     /     ACCOUNTS",
"WORKSPACE     /     TẠO {}": "WORKSPACE     /     CREATE {}",
"Xóa": "Delete",
"Xóa toàn bộ {} task trong hàng đợi này?": "Delete all {} tasks in this queue?",
"Xóa tài khoản": "Delete account",
"Xóa tài khoản {}? (Thư mục hồ sơ đăng nhập vẫn được giữ trên máy)": "Delete account {}? (Its login profile folder stays on this computer)",
"Xóa tất cả": "Delete all",
"Xóa {} task đã chọn?": "Delete {} selected tasks?",
"Xóa đã chọn": "Delete selected",
"[{}] Lỗi: {}": "[{}] Error: {}",
"[{}] Tạm dừng tài khoản vì lỗi liên tiếp. Kiểm tra đăng nhập ở mục Tài khoản.": "[{}] Account paused after repeated errors. Check the login on the Accounts page.",
"[{}] Việc {}: LỖI - {}": "[{}] Job {}: ERROR - {}",
"[{}] Việc {}: bắt đầu - {}": "[{}] Job {}: started - {}",
"[{}] Việc {}: xong, đã lưu {}": "[{}] Job {}: done, saved {}",
"[{}] Đã mở Chrome. Đăng nhập Muse trong cửa sổ đó rồi đóng cửa sổ lại (hoặc bấm 'Đóng trình duyệt').": "[{}] Chrome opened. Sign in to Muse in that window, then close it (or click 'Close browser').",
"{} lỗi": "{} errors",
"{} tệp trong {}": "{} files in {}",
"{} ảnh đã chọn": "{} images selected",
"{} ảnh, ghép theo thứ tự prompt": "{} images, paired in prompt order",
"{}/{} ảnh": "{}/{} images",
"Ô nhập prompt (CSS)": "Prompt input box (CSS)",
"Ô nhập và nút bấm": "Input box and buttons",
"Đang chạy": "Running",
"Đang chờ": "Queued",
"Đang có việc chạy nên chưa khởi động lại. Thay đổi sẽ áp dụng ở lần mở app sau.": "Jobs are running, so the app wasn't restarted. The change will apply the next time you open it.",
"Đã bấm Dừng tất cả.": "Stop all was pressed.",
"Đã có tài khoản tên này.": "An account with this name already exists.",
"Đã dừng.": "Stopped.",
"Đã hủy": "Cancelled",
"Đóng trình duyệt": "Close browser",
"Đăng nhập (mở Chrome)": "Log in (open Chrome)",
"Đưa mọi mục trong Cài đặt về giá trị ban đầu. Tài khoản, hàng đợi và thư mục thành phẩm được giữ nguyên.": "Resets every Settings item to its original value. Accounts, queue and the output folder are kept.",
"Đưa tất cả mục trong Cài đặt về giá trị mặc định?\n(Tài khoản, hàng đợi và thư mục thành phẩm không bị ảnh hưởng.)": "Reset all Settings items to their defaults?\n(Accounts, queue and the output folder are not affected.)",
"Đặt lại": "Reset",
"Đặt lại và dọn dẹp": "Reset and clean up",
"Để trống = nhấn Enter": "Empty = press Enter",
"ẢNH": "IMAGE",
"ẢNH THAM CHIẾU": "REF. IMAGES",
"Ảnh": "Image",
"Ảnh 1 ↔ prompt 1, ảnh 2 ↔ prompt 2...": "Image 1 ↔ prompt 1, image 2 ↔ prompt 2...",
"Ảnh dùng chung cho mọi prompt (tối đa {})": "Images shared by all prompts (max {})",
"Ảnh tham chiếu": "Reference images",
"Ảnh · {}": "Image · {}",
"↑ Nhập file TXT": "↑ Import TXT file",
"↻  Làm mới": "↻  Refresh",
"⌕   Tìm kiếm trong cài đặt  (Ctrl+F)": "⌕   Search settings  (Ctrl+F)",
"▶  Bắt đầu chạy": "▶  Start run",
"▶ Mở": "▶ Open",
"●  Đang chạy ({})": "●  Running ({})",
"● Chưa đăng nhập": "● Not logged in",
"● Đang chạy · {} luồng": "● Running · {} threads",
"● Đang mở Chrome để đăng nhập": "● Chrome open for login",
"● Đã có hồ sơ đăng nhập": "● Login profile saved",
"＋  Thêm tài khoản": "＋  Add account",
"＋ Gán ảnh": "＋ Assign images",
"📂  Mở thư mục": "📂  Open folder",
"📋 Sao chép": "📋 Copy",
"🖼 Mở": "🖼 Open",
"🖼 Xem ảnh": "🖼 View image",
"🗂 Thư mục debug": "🗂 Debug folder",
# --- chuỗi động / giá trị gốc tiếng Việt chỉ dịch lúc hiển thị ---
"không tên": "unnamed",
"chạy ngầm": "background",
"hiện cửa sổ": "visible window",
"Không thấy ô nhập prompt (trang: {}). Có thể cần đăng nhập lại": "Prompt input box not found (page: {}). You may need to log in again",
"Không tìm thấy ảnh tham chiếu: {}": "Reference image not found: {}",
"Không đính kèm được ảnh: {}": "Could not attach the image: {}",
"Không tìm thấy nút đính kèm ảnh (xem ảnh chụp trong thư mục debug)": "Attach-image button not found (see the screenshot in the debug folder)",
"Quá thời gian chờ: không thấy kết quả (xem thư mục debug)": "Timed out: no result found (see the debug folder)",
"Tải thất bại (HTTP {})": "Download failed (HTTP {})",
"Đã dừng": "Stopped",
"Bị gián đoạn": "Interrupted",
"Bị gián đoạn (tool đã đóng)": "Interrupted (the app was closed)",
"Lỗi không rõ": "Unknown error",
"5 giây": "5 sec", "10 giây": "10 sec", "15 giây": "15 sec", "20 giây": "20 sec", "30 giây": "30 sec",
"9:16 · Dọc": "9:16 · Portrait", "16:9 · Ngang": "16:9 · Landscape", "1:1 · Vuông": "1:1 · Square", "3:4 · Dọc": "3:4 · Portrait", "4:3 · Ngang": "4:3 · Landscape",
"Tối": "Dark", "Sáng": "Light", "Theo hệ thống": "Follow system",
"Chung": "General", "Prompt video": "Video prompt", "STT": "NO.",
"Đã tải bản cập nhật {}": "Downloaded update {}",
"Có bản cập nhật mới ({}).\nKhởi động lại Muse Studio để dùng ngay?": "A new version ({}) is available.\nRestart Muse Studio to use it now?",
"Có bản cập nhật": "Update available",
"Đang chạy việc nên chưa khởi động lại. Bản mới sẽ được dùng ở lần mở app sau.": "Jobs are running, so the app wasn't restarted. The new version will be used the next time you open it.",
}

# Chỉ các thông báo lỗi của app (do code tạo, có phần động) mới được dịch theo mẫu; chữ người dùng nhập thì không bao giờ bị đụng tới.
_DYN = ["Không thấy ô nhập prompt (trang: {}). Có thể cần đăng nhập lại", "Không tìm thấy ảnh tham chiếu: {}",
        "Không đính kèm được ảnh: {}", "Tải thất bại (HTTP {})"]
_TPL = []
if LANG == "English":
    for _k in _DYN:
        _TPL.append((re.compile("".join("(.*?)" if _p == "{}" else re.escape(_p) for _p in re.split(r"(\{\})", _k)), re.S), EN[_k]))

@functools.lru_cache(maxsize=4096)
def _tr_en(s):
    r = EN.get(s)
    if r is not None: return r
    for rx, tpl in _TPL:
        m = rx.fullmatch(s)
        if m: return tpl.format(*[_tr_en(g) for g in m.groups()])
    return s

def tr(s):
    """Dịch chữ hiển thị. Tiếng Việt: trả nguyên văn. Giá trị không phải chuỗi đi qua nguyên vẹn."""
    return _tr_en(s) if LANG == "English" and isinstance(s, str) and s else s

def choice_label(key, val): return tr(val) if key == "theme" else val
def choice_value(key, label):
    for o in CHOICES.get(key, []):
        if choice_label(key, o) == label: return o
    return label
def pick_opt(val, opts, kind):
    f = (lambda x: (re.findall(r"\d+", x) or [""])[0]) if kind == "dur" else (lambda x: x.split("·")[0].strip())
    k = f(str(val))
    for o in opts:
        if f(o) == k: return o
    return opts[0] if opts else val
DURS = [tr(x) for x in DURS_VI]
RATIOS = [tr(x) for x in RATIOS_VI]

def save_settings():
    try: json.dump(ST, open(CFG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception: pass

# ======================= Nhật ký / lỗi =======================
LOG = []
def elog(level, text): LOG.append((time.strftime("%H:%M:%S"), level, text))
def log_err():
    try: open(ERR_FILE, "a", encoding="utf-8").write(time.ctime() + "\n" + traceback.format_exc() + "\n")
    except Exception: pass
def first_line(e):
    lines = [l.strip() for l in str(e).splitlines() if l.strip()]
    return (lines[0] if lines else "Lỗi không rõ")[:90]

def explain(msg):
    m = (msg or "").lower()
    rules = [
        ("đã dừng", tr("Bạn đã bấm Dừng nên việc này bị bỏ dở. Bấm 'Gửi lại' hoặc 'Chạy lại task lỗi' để làm tiếp.")),
        ("đã hủy", tr("Việc này đã bị hủy theo yêu cầu của bạn.")),
        ("không thấy ô nhập prompt", tr("Có thể phiên đăng nhập đã hết hạn hoặc Muse hiện trang khác. Vào mục Tài khoản, bấm 'Đăng nhập', đăng nhập lại rồi chạy lại. Xem ảnh chụp trong thư mục debug (mục Nhật ký).")),
        ("đính kèm", tr("Tool không bấm được nút đính kèm ảnh của Muse. Thử đăng nhập lại; nếu vẫn lỗi, nhập CSS nút đính kèm trong Cài đặt hoặc gửi ảnh chụp trong thư mục debug cho người hỗ trợ.")),
        ("quá thời gian chờ", tr("Muse chưa trả kết quả theo dạng tool nhận ra được. Mở file jobNNN_info.txt trong thư mục debug để xem Muse đã trả lời gì; có thể Muse đang chậm, hãy thử gửi lại.")),
        ("has been closed", tr("Cửa sổ trình duyệt bị đóng giữa chừng. Đừng tắt Chrome khi tool đang chạy, rồi bấm 'Gửi lại'.")),
        ("http 401", tr("Link tải bị từ chối vì phiên đăng nhập hết hạn. Đăng nhập lại rồi chạy lại.")),
        ("http 403", tr("Link tải bị từ chối (link hết hạn hoặc cần đăng nhập). Đăng nhập lại rồi chạy lại.")),
        ("http 404", tr("Link tải không còn tồn tại. Thử gửi lại việc này.")),
        ("net::err", tr("Lỗi mạng hoặc link sai. Kiểm tra Internet và link Muse ở mục Tài khoản.")),
        ("timeout", tr("Trang tải quá chậm hoặc nút cần bấm không xuất hiện. Kiểm tra mạng và link rồi gửi lại.")),
        ("executable doesn't exist", tr("Chưa cài trình duyệt cho Playwright. Mở Command Prompt, chạy: playwright install chromium")),
        ("bị gián đoạn", tr("Tool bị đóng khi việc đang chạy. Bấm 'Gửi lại' (lưu ý: có thể Muse đã tạo sẵn video đó).")),
    ]
    for key, tip in rules:
        if key in m: return tip
    return tr("Chưa có gợi ý riêng cho lỗi này. Xem mục Nhật ký (error.log) và gửi cho người hỗ trợ.")

# ======================= Công việc (hàng đợi) =======================
LOCK = threading.RLock()
JOBS = []
S = {"running": False, "stop": False, "runs": set(), "seq": 0}   # runs = {(loại, người dùng)} đang được phép chạy
RUNTIME_KEYS = ("sel", "cancel", "t0", "_sig", "_th")

def clean_name(n): return re.sub(r'[\\/:*?"<>|]', "", n or "").strip()

def new_job(kind, prompt, dur, ratio, refs, user=""):
    with LOCK:
        S["seq"] += 1
        j = {"i": S["seq"], "kind": kind, "prompt": prompt, "dur": dur, "ratio": ratio, "refs": list(refs),
             "st": "queued", "err": "", "err_full": "", "file": "", "thumb": "", "acc": "", "sel": False, "user": user}
        JOBS.append(j); return j

def save_tasks():
    try:
        with LOCK: data = [{k: v for k, v in j.items() if k not in RUNTIME_KEYS} for j in JOBS]
        json.dump({"seq": S["seq"], "jobs": data}, open(TASK_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception: pass

def load_tasks():
    try:
        d = json.load(open(TASK_FILE, encoding="utf-8"))
        S["seq"] = d.get("seq", 0)
        for j in d.get("jobs", []):
            j.setdefault("thumb", ""); j.setdefault("acc", ""); j["sel"] = False
            if j["st"] == "run": j["st"] = "fail"; j["err"] = "Bị gián đoạn (tool đã đóng)"; j["err_full"] = j["err"]
            JOBS.append(j)
    except Exception: pass
load_tasks()

def take_job(acc):
    """Chia đều giữa các người dùng: ưu tiên người đang có ít việc chạy nhất (cùng mức thì theo thứ tự thêm vào)."""
    with LOCK:
        if S["stop"] or not S["running"]: return None
        cand = [j for j in JOBS if j["st"] == "queued" and (j["kind"], j.get("user", "")) in S["runs"]]
        if not cand: return None
        load = {}
        for j in JOBS:
            if j["st"] == "run": load[j.get("user", "")] = load.get(j.get("user", ""), 0) + 1
        j = min(cand, key=lambda x: (load.get(x.get("user", ""), 0), x["i"]))
        j["st"] = "run"; j["acc"] = acc; j["err"] = j["err_full"] = ""; j["t0"] = time.time(); j.pop("cancel", None)
        return j

def has_queued():
    with LOCK: return any(j["st"] == "queued" and (j["kind"], j.get("user", "")) in S["runs"] for j in JOBS)

# ======================= Tiện ích tệp / tải về =======================
SEEN, HASHES = set(), set()
def load_ignore():
    for f in os.listdir(IGNORE):
        try: HASHES.add(hashlib.sha1(open(os.path.join(IGNORE, f), "rb").read()).hexdigest())
        except Exception: pass
load_ignore()

def unique_path(base, ext):
    path = base + ext; n = 2
    while os.path.exists(path): path = f"{base}_{n}{ext}"; n += 1
    return path

def sniff_ext(data, kind):
    if data[:4] == b"\x89PNG": return ".png"
    if data[:3] == b"\xff\xd8\xff": return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP": return ".webp"
    if data[:3] == b"GIF": return ".gif"
    return ".png" if kind == "image" else ".mp4"

def webp_to_jpg(path):
    if not HAVE_PIL or not path.lower().endswith(".webp"): return path
    try:
        im = Image.open(path)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA"); bg = Image.new("RGB", im.size, "white"); bg.paste(im, mask=im.split()[-1]); im = bg
        else: im = im.convert("RGB")
        new = unique_path(os.path.splitext(path)[0], ".jpg"); im.save(new, "JPEG", quality=95); im.close(); os.remove(path)
        return new
    except Exception: return path

def thumb_path_for(path): return os.path.join(THUMBS, hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest() + ".jpg")

def make_thumb(path, kind):
    """Ảnh xem trước: ảnh thì dùng chính nó; video thì lấy 1 khung hình (opencv hoặc ffmpeg nếu có)."""
    if kind == "image": return path
    out = thumb_path_for(path)
    if os.path.exists(out): return out
    try:
        if HAVE_CV2:
            cap = cv2.VideoCapture(path); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if n > 12: cap.set(cv2.CAP_PROP_POS_FRAMES, min(n // 8, 30))
            ok, fr = cap.read(); cap.release()
            if ok:
                h, w = fr.shape[:2]; k = 240 / max(h, w)
                if k < 1: fr = cv2.resize(fr, (max(1, int(w * k)), max(1, int(h * k))))
                ok2, buf = cv2.imencode(".jpg", fr)
                if ok2: open(out, "wb").write(buf.tobytes()); return out
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", path, "-frames:v", "1", "-vf", "scale=240:-1", out],
                           timeout=40, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.path.exists(out): return out
    except Exception: pass
    return ""

def open_path(p):
    try:
        if hasattr(os, "startfile"): os.startfile(p)
        elif sys.platform == "darwin": subprocess.Popen(["open", p])
        else: subprocess.Popen(["xdg-open", p])
    except Exception:
        messagebox.showinfo(tr("Không mở được"), tr('Không mở được:\n{}').format(p))

# ======================= Tự động hóa trang Muse =======================
VIDEO_JS = r"""([sel, minW, anchor, kind]) => {
  let root = document;
  if (sel) { try { root = document.querySelector(sel) || document; } catch (e) {} }
  const norm = t => (t || '').replace(/\s+/g, ' ').trim();
  let an = null;
  if (anchor) {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const a = norm(anchor);
    while (w.nextNode()) { if (norm(w.currentNode.textContent).includes(a)) an = w.currentNode; }
  }
  const after = el => !an || (an.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const img = kind === 'image';
  const els = [...root.querySelectorAll(img ? 'img' : 'video')]
    .filter(v => !(img && v.closest('video')) && v.getBoundingClientRect().width >= minW && after(v));
  const vids = els.map(v => img ? (v.currentSrc || v.src) : (v.currentSrc || v.src || (v.querySelector('source') || {}).src));
  const links = img ? [] : [...root.querySelectorAll('a[href]')].filter(after).map(a => a.href)
    .filter(h => /\.(mp4|webm|mov)(\?|$)/i.test(h));
  return [...vids, ...links].filter(Boolean);
}"""

def video_srcs(page, root_sel="", min_w=0, anchor="", kind="video"):
    return page.evaluate(VIDEO_JS, [root_sel, min_w, anchor, kind])

def save_src(ctx, page, src, path):
    if src.startswith("data:"): data = base64.b64decode(src.split(",", 1)[1])
    elif src.startswith("blob:"):
        b64 = page.evaluate("""async s=>{const b=await (await fetch(s)).blob();
          return await new Promise(r=>{const f=new FileReader();f.onload=()=>r(f.result.split(',')[1]);f.readAsDataURL(b)})}""", src)
        data = base64.b64decode(b64)
    else:
        resp = ctx.request.get(src)
        if not resp.ok: raise Exception(f"Tải thất bại (HTTP {resp.status})")
        data = resp.body()
    open(path, "wb").write(data)

def shot(page, job, tag):
    try: os.makedirs(DEBUG, exist_ok=True); page.screenshot(path=os.path.join(DEBUG, f"job{job['i']:03d}_{tag}.png"))
    except Exception: pass

def dump_info(page, job, caught, imgs):
    try:
        os.makedirs(DEBUG, exist_ok=True)
        vids = page.evaluate("""[...document.querySelectorAll('video')].map(v=>({src:(v.currentSrc||v.src||'').slice(0,140),w:Math.round(v.getBoundingClientRect().width)}))""")
        im = page.evaluate("""[...document.querySelectorAll('img')].map(v=>({src:(v.currentSrc||v.src||'').slice(0,140),w:Math.round(v.getBoundingClientRect().width)})).filter(x=>x.w>=60).slice(-25)""")
        text = page.evaluate("(document.body.innerText||'').slice(-1200)")
        with open(os.path.join(DEBUG, f"job{job['i']:03d}_info.txt"), "w", encoding="utf-8") as f:
            f.write("URL: " + page.url + "\n\nVIDEO TRONG TRANG:\n" + "\n".join(map(str, vids)))
            f.write("\n\nANH TRONG TRANG:\n" + "\n".join(map(str, im)))
            f.write("\n\nVIDEO BAT DUOC TREN MANG:\n" + "\n".join(f"{u[:140]}: {n}" for u, n in caught.items()))
            f.write("\n\nANH BAT DUOC TREN MANG:\n" + "\n".join(f"{u[:140]}: {n}" for u, n in imgs.items()))
            f.write("\n\nCHU CUOI TRANG (Muse da noi gi):\n" + text)
    except Exception: pass

def attach_one(page, cfg, box, path):
    cands = ([cfg["attach_sel"].strip()] if cfg["attach_sel"].strip() else []) + [
        "button:has-text('+')", "[aria-label*='ttach' i]", "[aria-label*='pload' i]", "[aria-label*='ính kèm' i]", "[data-testid*='attach' i]"]
    locs = [page.locator(c).first for c in cands] + [box.locator("xpath=ancestor::*[.//button][1]//button").first]
    for loc in locs:
        try:
            if not loc.count(): continue
            try:
                with page.expect_file_chooser(timeout=4000) as fc: loc.click(timeout=4000)
                fc.value.set_files(path)
            except PWTimeout:
                item = page.get_by_text(re.compile(r"upload|tải|ảnh|image|photo|file|tệp|device|máy", re.I)).first
                with page.expect_file_chooser(timeout=6000) as fc2: item.click(timeout=4000)
                fc2.value.set_files(path)
            page.wait_for_timeout(2500); return
        except Exception:
            try: page.keyboard.press("Escape")
            except Exception: pass
    raise Exception("Không tìm thấy nút đính kèm ảnh (xem ảnh chụp trong thư mục debug)")

def attach_images(page, cfg, box, paths):
    inp = page.locator("input[type=file]")
    try:
        if inp.count():
            try: inp.first.set_input_files(paths)
            except Exception:
                for p in paths: inp.first.set_input_files(p); page.wait_for_timeout(1500)
            page.wait_for_timeout(2500 + 800 * len(paths)); return
    except Exception: pass
    for p in paths: attach_one(page, cfg, box, p)

def compose(job, cfg):
    if job["kind"] == "image": body = cfg["pfx_img"] + job["prompt"]; spec = cfg["spec_image"]
    else: body = (cfg["pfx_i2v"] if job["refs"] else "") + job["prompt"]; spec = cfg["spec_video"]
    try: spec = spec.format(dur=job["dur"], ratio=job["ratio"]) if spec.strip() else ""
    except Exception: spec = ""
    return body + spec

class Worker(threading.Thread):
    """Mỗi tài khoản một luồng riêng, một hồ sơ trình duyệt riêng; chạy nhiều tab (luồng) cùng lúc."""
    def __init__(self, acc):
        super().__init__(daemon=True)
        self.acc, self.q, self.ctx, self.visible, self.closed, self.state, self.p, self.anchor = acc, queue.Queue(), None, None, True, "idle", None, None
        self.start()
    @property
    def name(self): return self.acc["name"]

    def run(self):
        with sync_playwright() as p:
            self.p = p
            while True:
                cmd, arg = self.q.get()
                try:
                    if cmd == "login": self.login(arg)
                    elif cmd == "run": self.state = "running"; self.do_run(arg)
                    elif cmd == "close": self.close_ctx()
                    elif cmd == "exit": self.close_ctx(); return
                except Exception as e:
                    elog("err", tr('[{}] Lỗi: {}').format(self.name, tr(first_line(e)))); elog("hint", tr("Gợi ý: ") + explain(str(e))); log_err()
                finally:
                    if cmd == "run": self.state = "idle"; worker_done()

    def close_ctx(self):
        try:
            if self.ctx is not None: self.ctx.close()
        except Exception: pass
        self.ctx = self.anchor = None; self.closed = True

    def ensure(self, headless):
        if self.ctx is not None and not self.closed and self.visible == (not headless): return
        self.close_ctx(); os.makedirs(self.acc["profile"], exist_ok=True)
        if headless:
            kw = dict(headless=False, viewport={"width": 1366, "height": 900}, user_agent=UA, args=["--headless=new", "--window-size=1366,900"])
        else:
            kw = dict(headless=False, viewport=None)
        self.ctx = self.p.chromium.launch_persistent_context(self.acc["profile"], **kw)
        self.closed = False; self.visible = not headless
        self.ctx.on("close", lambda *_: setattr(self, "closed", True))
        self.anchor = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def login(self, url):
        self.ensure(False); self.anchor.goto(url)
        elog("info", tr("[{}] Đã mở Chrome. Đăng nhập Muse trong cửa sổ đó rồi đóng cửa sổ lại (hoặc bấm 'Đóng trình duyệt').").format(self.name))

    def pause(self, ms):
        try: self.anchor.wait_for_timeout(ms)
        except Exception: time.sleep(ms / 1000)

    # ---------- chạy hàng đợi ----------
    def do_run(self, cfg):
        acc, active, fails, last = self.name, [], 0, 0.0
        try:
            self.ensure(cfg["headless"])
            while not S["stop"]:
                while len(active) < cfg["threads"] and fails < 3 and time.time() - last >= cfg["delay"]:
                    job = take_job(acc)
                    if not job: break
                    last = time.time()
                    elog("info", tr('[{}] Việc {}: bắt đầu - {}').format(acc, job['i'], job['prompt'][:60]))
                    try: active.append(self.start_job(job, cfg))
                    except Exception as e: fails = self.fail(job, e, fails)
                if not active:
                    if fails >= 3:
                        elog("err", tr('[{}] Tạm dừng tài khoản vì lỗi liên tiếp. Kiểm tra đăng nhập ở mục Tài khoản.').format(acc)); break
                    if not has_queued(): break
                    self.pause(1000); continue
                for st in list(active):
                    try: r = self.poll(st, cfg)
                    except Exception as e:
                        active.remove(st); self.drop(st); fails = self.fail(st["job"], e, fails); continue
                    if r == "done":
                        active.remove(st); self.drop(st); fails = 0
                        elog("ok", tr('[{}] Việc {}: xong, đã lưu {}').format(acc, st['job']['i'], os.path.basename(st['job']['file'])))
                self.pause(2000)
        finally:
            for st in active:
                self.drop(st); self.fail(st["job"], Exception("Đã dừng" if S["stop"] else "Bị gián đoạn"), 0)

    def fail(self, job, e, fails):
        msg = str(e).strip()
        if "Đã hủy" in msg: job["st"] = "cancel"; job["err"] = ""; return fails
        job["st"] = "fail"; job["err"] = first_line(e); job["err_full"] = msg[:900]
        if "Đã dừng" in msg: return fails
        log_err(); elog("err", tr('[{}] Việc {}: LỖI - {}').format(self.name, job['i'], tr(job['err']))); elog("hint", tr("Gợi ý: ") + explain(msg))
        return fails + 1

    def drop(self, st):
        try: st["page"].remove_listener("response", st["on_resp"])
        except Exception: pass
        try: st["page"].close()
        except Exception: pass

    def start_job(self, job, cfg):
        kind = job["kind"]; page = self.ctx.new_page(); caught, imgs = {}, {}
        def on_resp(r):
            try:
                ct = (r.headers.get("content-type") or "").lower()
                if ct.startswith("image/") and "svg" not in ct:
                    imgs[r.url] = max(int(r.headers.get("content-length") or 0), imgs.get(r.url, 0)); return
                if ct.startswith("video/") or re.search(r"\.(mp4|webm|mov)(\?|$)", r.url, re.I):
                    n = int(r.headers.get("content-length") or 0); tot = (r.headers.get("content-range") or "").split("/")[-1]
                    if tot.isdigit(): n = int(tot)
                    caught[r.url] = max(n, caught.get(r.url, 0))
            except Exception: pass
        st = {"job": job, "page": page, "caught": caught, "imgs": imgs, "on_resp": on_resp}
        try:
            page.on("response", on_resp)
            page.goto(cfg["url"]); page.wait_for_load_state("domcontentloaded"); page.wait_for_timeout(2500)
            if cfg["newchat"].strip():
                try: page.locator(cfg["newchat"]).first.click(timeout=8000); page.wait_for_timeout(2000)
                except Exception: pass
            for key in (("dur_click",) if kind == "video" else ()) + ("ratio_click",):
                t = cfg[key].strip()
                if t:
                    try: page.get_by_text(t.format(dur=job["dur"], ratio=job["ratio"]), exact=False).first.click(timeout=3000); page.wait_for_timeout(500)
                    except Exception: pass
            st["flt"] = (cfg["result_sel"], cfg["min_w"])
            st["old"] = set(video_srcs(page, *st["flt"], "", kind)) | SEEN | set(caught) | set(imgs)
            box = page.locator(cfg["prompt_sel"]).first
            try: box.wait_for(state="visible", timeout=20000)
            except Exception:
                shot(page, job, "nobox"); dump_info(page, job, caught, imgs)
                raise Exception("Không thấy ô nhập prompt (trang: " + (page.title() or page.url)[:35] + "). Có thể cần đăng nhập lại")
            if job["refs"]:
                missing = [p for p in job["refs"] if not os.path.exists(p)]
                if missing: raise Exception("Không tìm thấy ảnh tham chiếu: " + os.path.basename(missing[0]))
                try: attach_images(page, cfg, box, job["refs"])
                except Exception as e: shot(page, job, "attach"); raise Exception("Không đính kèm được ảnh: " + first_line(e))
            box.click(); box.fill(compose(job, cfg))
            if cfg["gen_sel"].strip(): page.locator(cfg["gen_sel"]).first.click()
            else: box.press("Enter")
        except Exception:
            self.drop(st); raise
        busy = cfg["busy"].strip()
        st.update(pat=re.compile(r"^\W*" + re.escape(busy) + r"\W*$", re.I) if busy else None, t_sent=time.time(),
                  end=time.time() + cfg["timeout"], seen_busy=False, phase="gen" if busy else "collect", anchor_txt=job["prompt"][:50],
                  min_b=cfg["min_kb"] * 1024)
        return st

    def poll(self, st, cfg):
        job, page, kind, now = st["job"], st["page"], st["job"]["kind"], time.time()
        if S["stop"]: raise Exception("Đã dừng")
        if job.get("cancel"): raise Exception("Đã hủy")
        if st["phase"] == "gen":
            busy_now = bool(page.get_by_text(st["pat"]).count())
            st["seen_busy"] = st["seen_busy"] or busy_now
            if (not busy_now and (st["seen_busy"] or now - st["t_sent"] >= 25)) or now >= st["end"]:
                st["phase"] = "collect"; st["end"] = min(st["end"], now + 150)
            else: return "wait"
        new = [s for s in video_srcs(page, *st["flt"], st["anchor_txt"], kind) if s not in st["old"]]
        if not new and kind == "image":
            new = [u for _, u in sorted(((n, u) for u, n in st["imgs"].items() if u not in st["old"] and n >= 80 * 1024), reverse=True)]
        if not new and kind == "video":
            new = [u for _, u in sorted(((n, u) for u, n in st["caught"].items() if u not in st["old"] and n >= st["min_b"]), reverse=True)]
        if new:
            page.wait_for_timeout(3000); odir = os.path.join(cfg["out"], job["user"]) if job.get("user") else cfg["out"]; os.makedirs(odir, exist_ok=True)
            base = os.path.join(odir, f"{'image' if kind == 'image' else 'video'}_{job['i']:03d}"); tmp = base + ".part"
            for src in new:
                try: save_src(self.ctx, page, src, tmp)
                except Exception: st["old"].add(src); continue
                data = open(tmp, "rb").read(); h = hashlib.sha1(data).hexdigest()
                if h in HASHES or (kind == "image" and len(data) < 15000): st["old"].add(src); os.remove(tmp); continue
                HASHES.add(h); path = unique_path(base, sniff_ext(data, kind)); os.replace(tmp, path)
                if kind == "image": path = webp_to_jpg(path)
                job["file"] = path; job["thumb"] = make_thumb(path, kind)
                SEEN.update(video_srcs(page, "", 0, "", kind)); SEEN.update(st["caught"]); job["st"] = "done"; return "done"
        if now >= st["end"]:
            shot(page, job, "timeout"); dump_info(page, job, st["caught"], st["imgs"])
            raise Exception("Quá thời gian chờ: không thấy kết quả (xem thư mục debug)")
        return "wait"

WORKERS = {}
def get_worker(acc):
    w = WORKERS.get(acc["name"])
    if w is None: w = WORKERS[acc["name"]] = Worker(acc)
    return w

def worker_done():
    with LOCK:
        if all(w.state == "idle" for w in WORKERS.values()):
            S["running"] = False; S["runs"].clear()
            elog("info", tr("Đã dừng.") if S["stop"] else tr("Hoàn tất lượt chạy."))

def build_cfg(V):
    def num(k, cast, dv):
        try: return cast(str(V[k].get()).strip() or dv)
        except (ValueError, TypeError): return dv
    return {"url": V["url"].get().strip(), "out": V["out"].get().strip(), "headless": bool(ST.get("headless", True)),
            "threads": max(1, min(10, num("threads", int, 4))), "timeout": max(1.0, num("wait_min", float, 60.0)) * 60,
            "delay": max(0.0, float(ST.get("delay") or 5)), "prompt_sel": ST["ps"] or "textarea", "gen_sel": ST["send"], "attach_sel": ST["att"],
            "result_sel": ST["rs"].strip(), "min_w": int(ST["mw"] or 250), "busy": ST["busy"], "min_kb": int(ST["mk2"] or 1500),
            "newchat": ST["nc"], "pfx_img": ST["pfx_img"], "pfx_i2v": ST["pfx_i2v"], "spec_video": ST["spec_video"],
            "spec_image": ST["spec_image"], "dur_click": ST["dur_click"], "ratio_click": ST["ratio_click"]}

# ======================= Giao diện =======================
THEMES = ["Tối", "Sáng", "Theo hệ thống"]
def _resolve_theme():
    t = ST.get("theme", "Tối")
    if t == "Sáng": return "light"
    if t != "Theo hệ thống": return "dark"
    try:
        ctk.set_appearance_mode("system")
        return "light" if str(ctk.get_appearance_mode()).lower() == "light" else "dark"
    except Exception:
        return "dark"
THEME = _resolve_theme()
if THEME == "dark":
    BG, PANEL, PANEL2, LINE = "#0a1416", "#0f1c1f", "#142529", "#1e3538"
    INK, MUTE, ACC, ACC_H, ACC_TXT = "#e8f3f2", "#7f9b9c", "#5fe3c0", "#46c6a5", "#062b24"
    RED, RED_SOFT, AMB, AMB_SOFT, OK_SOFT, SEL = "#ff7b7b", "#3a1c20", "#f5b942", "#3a2f12", "#0f3a32", "#143a36"
    HOVER, SEL_H, RED_H, PHT, RUN_BG, RUN_FG, CAN_BG = "#2a4a4e", "#1c4a45", "#4a2428", "#5d7778", "#10303a", "#6ad0ff", "#243033"
    LOGC = {"err": "#ff9b9b", "ok": "#75e0a7", "hint": "#fedf89", "info": "#b8cccc"}
else:
    BG, PANEL, PANEL2, LINE = "#eef3f3", "#ffffff", "#f1f6f6", "#d4e1e1"
    INK, MUTE, ACC, ACC_H, ACC_TXT = "#102426", "#5f7a7c", "#0e9f7e", "#0b8268", "#ffffff"
    RED, RED_SOFT, AMB, AMB_SOFT, OK_SOFT, SEL = "#d03a3a", "#fbe4e4", "#a86a00", "#fcefcf", "#d6f3ea", "#d8efe8"
    HOVER, SEL_H, RED_H, PHT, RUN_BG, RUN_FG, CAN_BG = "#c9dada", "#c3e6dc", "#f6cccc", "#8aa2a3", "#dcedf7", "#1b78a8", "#e3eaea"
    LOGC = {"err": "#c62828", "ok": "#17803f", "hint": "#9a6700", "info": "#3d5a5c"}
BADGE = {"queued": (tr("Đang chờ"), AMB_SOFT, AMB), "run": (tr("Đang chạy"), RUN_BG, RUN_FG), "done": (tr("Hoàn tất"), OK_SOFT, ACC),
         "fail": (tr("Lỗi"), RED_SOFT, RED), "cancel": (tr("Đã hủy"), CAN_BG, MUTE)}
STATUS_FILTER = {tr("Tất cả trạng thái"): None, tr("Đang chờ"): "queued", tr("Đang chạy"): "run", tr("Hoàn tất"): "done", tr("Lỗi"): "fail", tr("Đã hủy"): "cancel"}
FN = lambda s=12, w="normal": ctk.CTkFont(family="Segoe UI", size=s, weight=w)
TKF = lambda s=9, w="normal": ("Segoe UI", s, w)
PH = {"video": tr("Một con phố Tokyo dưới mưa, ánh đèn neon...\nCảnh biển lúc bình minh, camera tiến chậm..."),
      "image": tr("Một chú mèo phi hành gia trên mặt trăng, phong cách điện ảnh...\nChân dung cô gái dưới ánh hoàng hôn, màu phim...")}
_PHOTOS = {}

def photo(path, box=(52, 40)):
    if not HAVE_PIL or not path or not os.path.exists(path): return None
    key = (path, box)
    if key not in _PHOTOS:
        try:
            im = Image.open(path).convert("RGB"); im.thumbnail((box[0] * 2, box[1] * 2)); im = im.resize((max(1, im.width // 2), max(1, im.height // 2)))
            _PHOTOS[key] = ImageTk.PhotoImage(im)
        except Exception: _PHOTOS[key] = None
    return _PHOTOS[key]

def clabel(parent, text, cmd, bg, fg, font=None, padx=8, pady=3):
    l = tk.Label(parent, text=text, bg=bg, fg=fg, font=font or TKF(9, "bold"), padx=padx, pady=pady, cursor="hand2")
    l._cmd = cmd; l._on = True
    l.bind("<Button-1>", lambda e: l._cmd() if l._on else None); return l

def set_enabled(l, on, fg_on, fg_off=MUTE):
    l._on = on; l.configure(fg=fg_on if on else fg_off, cursor="hand2" if on else "arrow")

def show_text(root, title, text):
    top = ctk.CTkToplevel(root); top.title(title); top.geometry("640x420"); top.configure(fg_color=PANEL); top.transient(root)
    tb = ctk.CTkTextbox(top, fg_color=PANEL2, text_color=INK, font=FN(13), wrap="word", corner_radius=10); tb.pack(fill="both", expand=True, padx=16, pady=(16, 8))
    tb.insert("1.0", text); tb.configure(state="disabled")
    def cp(): root.clipboard_clear(); root.clipboard_append(text)
    ctk.CTkButton(top, text=tr("Sao chép"), width=110, fg_color=PANEL2, hover_color=LINE, text_color=INK, command=cp).pack(side="right", padx=16, pady=(0, 14))
    top.after(200, top.focus_force)

def natkey(x): return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(x))]

def parse_prompts(text, multi):
    text = text.replace("\r", "")
    if multi: return [re.sub(r"[ \t]*\n[ \t]*", " ", b).strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    return [l.strip() for l in text.split("\n") if l.strip()]

def read_text_file(path):
    for enc in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
        try: return open(path, encoding=enc).read()
        except Exception: continue
    return ""

class CreatePage(ctk.CTkFrame):
    """Trang 'Tạo video' / 'Tạo ảnh': thiết lập đợt chạy + nhập prompt + hàng đợi."""
    def __init__(self, app, kind):
        super().__init__(app.content, fg_color="transparent")
        self.app, self.kind, self.V = app, kind, app.V
        self.video = kind == "video"; self.shared = []; self.paired = []; self.multi = False; self.rows = {}; self.vis_key = None
        self.dur_var = ctk.StringVar(value=pick_opt(ST.get("dur_video", DEF["dur_video"]), DURS, "dur"))
        self.ratio_var = ctk.StringVar(value=pick_opt(ST.get("ratio_video" if self.video else "ratio_image", DEF["ratio_video"]), RATIOS, "ratio"))
        self.sel_all = tk.BooleanVar(value=False); self.all_users = tk.BooleanVar(value=False); self.flt_s = ctk.StringVar(value=tr("Tất cả trạng thái"))
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(3, weight=1)
        T = "VIDEO" if self.video else tr("ẢNH")
        # --- đầu trang ---
        ctk.CTkLabel(self, text=tr('WORKSPACE     /     TẠO {}').format(tr(T)), font=FN(11, "bold"), text_color=MUTE).grid(row=0, column=0, sticky="w", padx=4, pady=(8, 0))
        hd = ctk.CTkFrame(self, fg_color="transparent"); hd.grid(row=1, column=0, sticky="ew", pady=(10, 12))
        ctk.CTkLabel(hd, text=tr('Tạo {}').format(tr(T.lower())), font=FN(24, "bold"), text_color=INK).pack(side="left", padx=4)
        self.btn_run = ctk.CTkButton(hd, text=tr("▶  Bắt đầu chạy"), height=38, width=150, corner_radius=10, font=FN(13, "bold"), fg_color=ACC, hover_color=ACC_H, text_color=ACC_TXT, command=lambda: app.start_run(kind))
        self.btn_run.pack(side="right")
        ctk.CTkButton(hd, text=tr("Dừng tất cả"), height=38, width=120, corner_radius=10, font=FN(13, "bold"), fg_color=PANEL2, hover_color=LINE, text_color=INK, command=app.stop_all).pack(side="right", padx=8)
        # --- thống kê ---
        sb = ctk.CTkFrame(self, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=12); sb.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.stat = {}
        for c, (k, t, col) in enumerate((("all", tr("Tổng tác vụ"), INK), ("queued", tr("Đang chờ"), AMB), ("done", tr("Hoàn tất"), ACC), ("fail", tr("Cần xử lý"), RED))):
            sb.grid_columnconfigure(c, weight=1, uniform="st")
            cell = ctk.CTkFrame(sb, fg_color="transparent"); cell.grid(row=0, column=c, sticky="ew", padx=16, pady=12)
            ctk.CTkLabel(cell, text=t, font=FN(12), text_color=MUTE).pack(side="left")
            self.stat[k] = ctk.CTkLabel(cell, text="0", font=FN(22, "bold"), text_color=col); self.stat[k].pack(side="right")
        # --- thân ---
        body = ctk.CTkFrame(self, fg_color="transparent"); body.grid(row=3, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1); body.grid_rowconfigure(0, weight=1)
        self.build_left(body, T); self.build_queue(body, T)

    def sec_head(self, parent, num, title, right=""):
        h = ctk.CTkFrame(parent, fg_color="transparent"); h.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(h, text=num, font=FN(11, "bold"), text_color=ACC, fg_color=SEL, corner_radius=6, width=28, height=24).pack(side="left")
        ctk.CTkLabel(h, text=title, font=FN(14, "bold"), text_color=INK).pack(side="left", padx=10)
        if right: ctk.CTkLabel(h, text=right, font=FN(11, "bold"), text_color=ACC).pack(side="right")

    def field(self, parent, r, c, label, widget_fn, colspan=1):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.grid(row=r, column=c, columnspan=colspan, sticky="ew", padx=(0 if c == 0 else 6, 0 if (c + colspan) >= 2 else 6), pady=(0, 8))
        ctk.CTkLabel(f, text=label, font=FN(11), text_color=MUTE).pack(anchor="w", pady=(0, 3)); w = widget_fn(f); w.pack(fill="x"); return w

    def build_left(self, body, T):
        lp = ctk.CTkFrame(body, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14, width=372); lp.grid(row=0, column=0, sticky="ns", padx=(0, 12)); lp.pack_propagate(False)
        self.sec_head(lp, "01", tr("Thiết lập đợt chạy"), T)
        g = ctk.CTkFrame(lp, fg_color="transparent"); g.pack(fill="x", padx=16); g.grid_columnconfigure((0, 1), weight=1, uniform="g")
        om = dict(height=34, corner_radius=8, font=FN(12, "bold"), fg_color=PANEL2, button_color=LINE, button_hover_color=HOVER, dropdown_fg_color=PANEL2, dropdown_text_color=INK, text_color=INK, dropdown_hover_color=LINE)
        en = dict(height=34, corner_radius=8, fg_color=PANEL2, border_color=LINE, text_color=INK, font=FN(12, "bold"))
        r = 0
        if self.video:
            self.field(g, 0, 0, tr("Thời lượng"), lambda f: ctk.CTkOptionMenu(f, values=DURS, variable=self.dur_var, command=lambda v: self.persist(), **om))
            self.field(g, 0, 1, tr("Khung hình"), lambda f: ctk.CTkOptionMenu(f, values=RATIOS, variable=self.ratio_var, command=lambda v: self.persist(), **om)); r = 1
        else:
            self.field(g, 0, 0, tr("Khung hình"), lambda f: ctk.CTkOptionMenu(f, values=RATIOS, variable=self.ratio_var, command=lambda v: self.persist(), **om), 2); r = 1
        self.field(g, r, 0, tr("Số luồng / tài khoản"), lambda f: ctk.CTkEntry(f, textvariable=self.V["threads"], **en))
        self.field(g, r, 1, tr("Chờ tối đa (phút)"), lambda f: ctk.CTkEntry(f, textvariable=self.V["wait_min"], **en))
        self.field(g, r + 1, 0, tr("Tên người dùng (mỗi người một thư mục riêng)"), lambda f: ctk.CTkEntry(f, textvariable=self.V["user"], placeholder_text="vd: Lan", **en), 2)
        self.field(g, r + 2, 0, tr('Thư mục gốc lưu {}').format(tr(T.lower())), lambda f: ctk.CTkEntry(f, textvariable=self.V["out"], **en), 2)
        ctk.CTkButton(lp, text=tr("Chọn thư mục..."), height=30, width=120, corner_radius=8, font=FN(12, "bold"), fg_color=PANEL2, hover_color=LINE, text_color=ACC,
                      command=lambda: (lambda d: d and self.V["out"].set(d))(filedialog.askdirectory())).pack(anchor="w", padx=16, pady=(0, 2))
        self.path_lbl = ctk.CTkLabel(lp, text="", font=FN(10), text_color=MUTE, anchor="w", wraplength=340, justify="left"); self.path_lbl.pack(anchor="w", padx=16)
        self.sec_head(lp, "02", tr("Nhập prompt"))
        seg = ctk.CTkSegmentedButton(lp, values=[tr("1 dòng / prompt"), tr("Nhiều dòng / prompt")], command=self.set_multi, height=32, font=FN(11, "bold"),
                                     fg_color=PANEL2, selected_color=SEL, selected_hover_color=SEL, unselected_color=PANEL2, unselected_hover_color=LINE, text_color=ACC)
        seg.set(tr("1 dòng / prompt")); seg.pack(fill="x", padx=16)
        ctk.CTkButton(lp, text=tr("+  Thêm vào hàng đợi"), height=42, corner_radius=10, font=FN(13, "bold"), fg_color=ACC, hover_color=ACC_H, text_color=ACC_TXT, command=self.add).pack(side="bottom", fill="x", padx=16, pady=14)
        sh = ctk.CTkFrame(lp, fg_color=PANEL2, border_color=LINE, border_width=1, corner_radius=10); sh.pack(side="bottom", fill="x", padx=16)
        ctk.CTkLabel(sh, text=tr('Ảnh dùng chung cho mọi prompt (tối đa {})').format(MAX_REFS), font=FN(12, "bold"), text_color=INK).pack(anchor="w", padx=10, pady=(8, 2))
        sr = ctk.CTkFrame(sh, fg_color="transparent"); sr.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(sr, text=tr("Chọn Tệp"), width=100, height=26, corner_radius=6, fg_color=LINE, hover_color=HOVER, text_color=INK, font=FN(11, "bold"), command=self.pick_shared).pack(side="left")
        self.shared_lbl = ctk.CTkLabel(sr, text=tr("Không tệp nào được chọn"), font=FN(11), text_color=MUTE); self.shared_lbl.pack(side="left", padx=8)
        self.shared_x = ctk.CTkButton(sr, text="✕", width=26, height=26, fg_color="transparent", hover_color=RED_SOFT, text_color=RED, command=self.clear_shared)
        pr = ctk.CTkFrame(sh, fg_color="transparent"); pr.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(pr, text=tr("Ghép ảnh theo prompt"), width=190, height=26, corner_radius=6, fg_color=SEL, hover_color=SEL_H, text_color=ACC, font=FN(11, "bold"), command=self.pick_paired).pack(side="left")
        self.paired_lbl = ctk.CTkLabel(pr, text=tr("Ảnh 1 ↔ prompt 1, ảnh 2 ↔ prompt 2..."), font=FN(11), text_color=MUTE); self.paired_lbl.pack(side="left", padx=8)
        self.paired_x = ctk.CTkButton(pr, text="✕", width=26, height=26, fg_color="transparent", hover_color=RED_SOFT, text_color=RED, command=self.clear_paired)
        bar = ctk.CTkFrame(lp, fg_color="transparent"); bar.pack(side="bottom", fill="x", padx=16, pady=(6, 8))
        ctk.CTkButton(bar, text=tr("↑ Nhập file TXT"), height=24, width=150, fg_color="transparent", hover_color=PANEL2, text_color=ACC, font=FN(12, "bold"), anchor="w", command=self.load_txt).pack(side="left")
        self.cnt = ctk.CTkLabel(bar, text="0 prompt", font=FN(12), text_color=MUTE); self.cnt.pack(side="right")
        tw = ctk.CTkFrame(lp, fg_color="transparent"); tw.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        self.tb = ctk.CTkTextbox(tw, fg_color=PANEL2, border_color=LINE, border_width=1, text_color=INK, font=FN(12), wrap="word", corner_radius=10, height=90); self.tb.pack(fill="both", expand=True)
        self.ph = ctk.CTkLabel(self.tb, text=PH[self.kind], font=FN(12), text_color=PHT, justify="left", anchor="nw", fg_color=PANEL2); self.ph.place(x=8, y=8)
        for ev in ("<KeyRelease>", "<ButtonRelease>", "<FocusIn>", "<FocusOut>"): self.tb.bind(ev, self.upd)
        self.ph.bind("<Button-1>", lambda e: self.tb.focus_set())

    def build_queue(self, body, T):
        qp = ctk.CTkFrame(body, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14); qp.grid(row=0, column=1, sticky="nsew")
        h = ctk.CTkFrame(qp, fg_color="transparent"); h.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(h, text="03", font=FN(11, "bold"), text_color=ACC, fg_color=SEL, corner_radius=6, width=28, height=24).pack(side="left")
        ctk.CTkLabel(h, text=tr('Hàng đợi {}').format(tr(T.lower())), font=FN(14, "bold"), text_color=INK).pack(side="left", padx=10)
        self.chip = ctk.CTkLabel(h, text="0 task", font=FN(11, "bold"), text_color=ACC, fg_color=SEL, corner_radius=12, height=26, width=70); self.chip.pack(side="right")
        tl = tk.Frame(qp, bg=PANEL); tl.pack(fill="x", padx=16, pady=(0, 6))
        tk.Checkbutton(tl, text=tr("Chọn tất cả"), variable=self.sel_all, command=self.toggle_all, bg=PANEL, fg=INK, selectcolor=PANEL2, activebackground=PANEL, activeforeground=INK, font=TKF(9), bd=0, highlightthickness=0).pack(side="left")
        for t, fg, cmd in ((tr("Hủy đã chọn"), ACC, self.cancel_sel), (tr("Xóa đã chọn"), RED, self.del_sel), (tr("Xóa tất cả"), RED, self.del_all), (tr("Chạy lại task lỗi"), ACC, self.retry_failed)):
            clabel(tl, t, cmd, PANEL, fg, TKF(9, "bold"), padx=6).pack(side="left")
        tk.Checkbutton(tl, text=tr("Mọi người dùng"), variable=self.all_users, command=lambda: self.sync(True), bg=PANEL, fg=MUTE, selectcolor=PANEL2, activebackground=PANEL, activeforeground=INK, font=TKF(9), bd=0, highlightthickness=0).pack(side="right", padx=(0, 8))
        ctk.CTkOptionMenu(tl, values=list(STATUS_FILTER), variable=self.flt_s, width=150, height=28, corner_radius=8, font=FN(11), fg_color=PANEL2, button_color=LINE, dropdown_fg_color=PANEL2, text_color=INK, dropdown_text_color=INK, command=lambda v: self.sync(True)).pack(side="right")
        se = self.search = ctk.CTkEntry(tl, placeholder_text=tr("Tìm prompt, tài khoản..."), width=190, height=28, corner_radius=8, fg_color=PANEL2, border_color=LINE, text_color=INK, font=FN(11)); se.pack(side="right", padx=8)
        se.bind("<KeyRelease>", lambda e: self.sync(True))
        self.cols = [(28, 0), (34, 0), (80, 0), (92, 0), (160, 1), (196, 0), (190, 0)]
        hd = tk.Frame(qp, bg=PANEL); hd.pack(fill="x", padx=(16, 30), pady=(4, 0)); self.grid_cols(hd)
        for c, t in enumerate(("", tr("STT"), tr("LOẠI"), tr("ẢNH THAM CHIẾU"), "PROMPT", tr("TIẾN TRÌNH"), tr("THAO TÁC"))):
            tk.Label(hd, text=t, bg=PANEL, fg=MUTE, font=TKF(8, "bold"), anchor="w").grid(row=0, column=c, sticky="w", padx=4, pady=6)
        tk.Frame(qp, bg=LINE, height=1).pack(fill="x", padx=16)
        self.list = ctk.CTkScrollableFrame(qp, fg_color="transparent", corner_radius=0, scrollbar_button_color=LINE, scrollbar_button_hover_color=HOVER); self.list.pack(fill="both", expand=True, padx=(12, 8), pady=(0, 10))

    def grid_cols(self, fr):
        for c, (w, wt) in enumerate(self.cols): fr.grid_columnconfigure(c, minsize=w, weight=wt)

    # ---------- nhập liệu ----------
    def persist(self):
        ST["dur_video"] = self.dur_var.get() if self.video else ST.get("dur_video", DEF["dur_video"])
        ST["ratio_video" if self.video else "ratio_image"] = self.ratio_var.get()

    def set_multi(self, v): self.multi = v == tr("Nhiều dòng / prompt"); self.upd()
    def prompts(self): return parse_prompts(self.tb.get("1.0", "end"), self.multi)
    def upd(self, *_):
        has = bool(self.tb.get("1.0", "end").strip())
        if has: self.ph.place_forget()
        else: self.ph.place(x=8, y=8)
        self.cnt.configure(text=f"{len(self.prompts())} prompt")
    def load_txt(self):
        p = filedialog.askopenfilename(title=tr("Chọn file prompt"), filetypes=[(tr("Văn bản"), "*.txt"), ("CSV", "*.csv"), (tr("Tất cả"), "*.*")])
        if not p: return
        raw = read_text_file(p)
        if p.lower().endswith(".csv"): raw = "\n".join(r[0].strip() for r in csv.reader(raw.splitlines()) if r and r[0].strip())
        cur = self.tb.get("1.0", "end").strip()
        if cur and not messagebox.askyesno(tr("Nhập file"), tr("Thay thế nội dung hiện tại?\n(Chọn 'Không' để nối thêm vào cuối)")): raw = cur + ("\n\n" if self.multi else "\n") + raw.strip()
        self.tb.delete("1.0", "end"); self.tb.insert("1.0", raw.strip()); self.upd()
    def pick_shared(self):
        fs = filedialog.askopenfilenames(title=tr("Chọn ảnh dùng chung"), filetypes=[(tr("Ảnh"), "*.png *.jpg *.jpeg *.webp *.bmp"), (tr("Tất cả"), "*.*")])
        if not fs: return
        if len(fs) > MAX_REFS: messagebox.showinfo(tr("Quá nhiều ảnh"), tr('Chỉ lấy {} ảnh đầu tiên.').format(MAX_REFS)); fs = fs[:MAX_REFS]
        self.shared = list(fs); self.shared_lbl.configure(text=tr('{} ảnh đã chọn').format(len(fs)), text_color=ACC); self.shared_x.pack(side="right")
    def pick_paired(self):
        fs = filedialog.askopenfilenames(title=tr("Chọn ảnh (ảnh thứ k dùng cho prompt thứ k)"), filetypes=[(tr("Ảnh"), "*.png *.jpg *.jpeg *.webp *.bmp"), (tr("Tất cả"), "*.*")])
        if not fs: return
        self.paired = sorted(fs, key=natkey); self.paired_lbl.configure(text=tr('{} ảnh, ghép theo thứ tự prompt').format(len(fs)), text_color=ACC); self.paired_x.pack(side="right")
    def clear_paired(self):
        self.paired = []; self.paired_lbl.configure(text=tr("Ảnh 1 ↔ prompt 1, ảnh 2 ↔ prompt 2..."), text_color=MUTE); self.paired_x.pack_forget()
    def assign_images(self, j):
        if j["st"] == "run": return messagebox.showinfo(tr("Đang chạy"), tr("Task đang chạy, chưa gán lại ảnh được."))
        if j["refs"]:
            a = messagebox.askyesnocancel(tr("Ảnh tham chiếu"), tr('Task này có {} ảnh.\n\nCó = chọn ảnh mới thay thế\nKhông = xóa hết ảnh\nHủy = giữ nguyên').format(len(j['refs'])))
            if a is None: return
            if a is False: j["refs"] = []; save_tasks(); return
        fs = filedialog.askopenfilenames(title=tr('Chọn ảnh cho prompt #{} (tối đa {})').format(j['i'], MAX_REFS), filetypes=[(tr("Ảnh"), "*.png *.jpg *.jpeg *.webp *.bmp"), (tr("Tất cả"), "*.*")])
        if fs: j["refs"] = list(fs)[:MAX_REFS]; save_tasks()
    def clear_shared(self):
        self.shared = []; self.shared_lbl.configure(text=tr("Không tệp nào được chọn"), text_color=MUTE); self.shared_x.pack_forget()
    def add(self):
        ps = self.prompts(); user = clean_name(self.V["user"].get())
        if not user: return messagebox.showinfo(tr("Thiếu tên người dùng"), tr("Hãy nhập Tên người dùng để video lưu vào thư mục riêng, tránh bị lộn với người khác."))
        if not ps: return messagebox.showinfo(tr("Thiếu prompt"), tr("Hãy nhập hoặc nạp file ít nhất một prompt."))
        try: dur = int(re.findall(r"\d+", self.dur_var.get())[0])
        except Exception: dur = 10
        ratio = self.ratio_var.get().split("·")[0].strip()
        if self.paired and len(self.paired) != len(ps) and not messagebox.askyesno(tr("Số lượng khác nhau"), tr('Có {} prompt nhưng {} ảnh ghép.\nẢnh được ghép theo thứ tự; prompt nào không có ảnh sẽ chạy không ảnh. Tiếp tục?').format(len(ps), len(self.paired))): return
        for k, p in enumerate(ps):
            refs = ([self.paired[k]] if k < len(self.paired) else []) + self.shared
            new_job(self.kind, p, dur if self.video else 0, ratio, refs[:MAX_REFS], user)
        self.clear_paired(); self.tb.delete("1.0", "end"); self.upd(); self.sync(True); save_tasks()

    # ---------- thao tác hàng loạt ----------
    def cur_user(self): return clean_name(self.V["user"].get())
    def mine(self):
        u = self.cur_user(); allu = self.all_users.get() or not u
        with LOCK: return [j for j in JOBS if j["kind"] == self.kind and (allu or j.get("user", "") == u)]
    def selected(self): return [j for j in self.mine() if j.get("sel")]
    def toggle_all(self):
        for j in self.visible(): j["sel"] = self.sel_all.get()
        for jid, w in self.rows.items(): w["var"].set(self.sel_all.get() and w["job"] in self.visible())
    def cancel_sel(self):
        for j in self.selected():
            if j["st"] == "queued": j["st"] = "cancel"
            elif j["st"] == "run": j["cancel"] = True
    def remove(self, jobs):
        with LOCK:
            for j in jobs:
                if j["st"] == "run": j["cancel"] = True
                if j in JOBS: JOBS.remove(j)
            if not JOBS: S["seq"] = 0
        self.vis_key = None; save_tasks()
    def del_sel(self):
        sel = self.selected()
        if sel and messagebox.askyesno(tr("Xóa"), tr('Xóa {} task đã chọn?').format(len(sel))): self.remove(sel)
    def del_all(self):
        m = self.mine()
        if m and messagebox.askyesno(tr("Xóa tất cả"), tr('Xóa toàn bộ {} task trong hàng đợi này?').format(len(m))): self.remove(m)
    def retry_failed(self):
        bad = [j for j in self.mine() if j["st"] == "fail"]
        if not bad: return messagebox.showinfo(tr("Không có lỗi"), tr("Không có task nào bị lỗi."))
        for j in bad: j["st"] = "queued"; j["err"] = j["err_full"] = ""
        for u in sorted({j.get("user", "") for j in bad}): self.app.start_run(self.kind, user=u)
    def resend(self, j):
        if j["st"] == "run": return
        j.update(st="queued", err="", err_full=""); self.app.start_run(self.kind, quiet=True, user=j.get("user", ""))
    def delete_one(self, j): self.remove([j])
    def save_copy(self, j):
        if not (j["file"] and os.path.exists(j["file"])): return
        d = filedialog.asksaveasfilename(initialfile=os.path.basename(j["file"]), defaultextension=os.path.splitext(j["file"])[1])
        if d: shutil.copy2(j["file"], d)

    # ---------- bảng hàng đợi ----------
    def visible(self):
        q, st = self.search.get().strip().lower(), STATUS_FILTER.get(self.flt_s.get())
        return [j for j in self.mine() if (not st or j["st"] == st) and (not q or q in j["prompt"].lower() or q in (j.get("acc") or "").lower() or q in (j.get("user") or "").lower())]

    def make_row(self, j):
        fr = tk.Frame(self.list, bg=PANEL); fr.pack(fill="x"); self.grid_cols(fr)
        sep = tk.Frame(self.list, bg=LINE, height=1); sep.pack(fill="x")
        w = {"job": j, "fr": fr, "sep": sep, "var": tk.BooleanVar(value=bool(j.get("sel")))}
        def tog(): j["sel"] = w["var"].get()
        tk.Checkbutton(fr, variable=w["var"], command=tog, bg=PANEL, selectcolor=PANEL2, activebackground=PANEL, bd=0, highlightthickness=0).grid(row=0, column=0, padx=2, pady=10)
        tk.Label(fr, text=str(j["i"]), bg=PANEL, fg=MUTE, font=TKF(9)).grid(row=0, column=1, sticky="w", padx=4)
        typ = f"{j['dur']}s · {j['ratio']}" if j["kind"] == "video" else tr('Ảnh · {}').format(j['ratio'])
        tk.Label(fr, text=typ, bg=PANEL2, fg=INK, font=TKF(8, "bold"), padx=6, pady=3).grid(row=0, column=2, sticky="w", padx=4)
        w["refs"] = clabel(fr, "", lambda: self.assign_images(j), PANEL, MUTE, TKF(8, "bold"), padx=2); w["refs"].grid(row=0, column=3, sticky="w", padx=4)
        pf = tk.Frame(fr, bg=PANEL); pf.grid(row=0, column=4, sticky="ew", padx=4); pf.grid_columnconfigure(0, weight=1)
        t = j["prompt"]; tk.Label(pf, text=(t[:90] + "…") if len(t) > 90 else t, bg=PANEL, fg=INK, font=TKF(9), anchor="w", justify="left", wraplength=210).grid(row=0, column=0, sticky="w")
        clabel(pf, "👁", lambda: show_text(self.app.root, f"Prompt #{j['i']}", j["prompt"]), SEL, ACC, TKF(10), padx=7, pady=4).grid(row=0, column=1, padx=(6, 0))
        pg = tk.Frame(fr, bg=PANEL); pg.grid(row=0, column=5, sticky="w", padx=4, pady=6)
        w["badge"] = tk.Label(pg, bg=PANEL, font=TKF(8, "bold"), padx=6, pady=2); w["badge"].pack(anchor="w")
        w["acc"] = tk.Label(pg, bg=PANEL, fg=MUTE, font=TKF(8), anchor="w"); w["acc"].pack(anchor="w")
        w["res"] = tk.Frame(pg, bg=PANEL)
        w["th"] = tk.Label(w["res"], bg=PANEL2, fg=MUTE, text="🎬" if j["kind"] == "video" else "🖼", width=7, height=3, font=TKF(9)); w["th"].pack(side="left")
        w["view"] = clabel(w["res"], "▶ Xem video" if j["kind"] == "video" else tr("🖼 Xem ảnh"), lambda: j["file"] and open_path(j["file"]), PANEL2, INK, TKF(8, "bold")); w["view"].pack(side="left", padx=6)
        w["err"] = tk.Label(pg, bg=PANEL, fg=RED, font=TKF(8), anchor="w", cursor="hand2", wraplength=200, justify="left")
        w["err"].bind("<Button-1>", lambda e: show_text(self.app.root, tr('Chi tiết lỗi - việc {}').format(j['i']), tr(j.get("err_full") or j["err"]) + tr("\n\nGợi ý: ") + explain(j.get("err_full") or j["err"])))
        af = tk.Frame(fr, bg=PANEL); af.grid(row=0, column=6, sticky="w", padx=4)
        w["open"] = clabel(af, "↗", lambda: j["file"] and open_path(j["file"]), PANEL, ACC, TKF(11), padx=5); w["open"].pack(side="left")
        w["dl"] = clabel(af, "↓", lambda: self.save_copy(j), PANEL, ACC, TKF(11), padx=5); w["dl"].pack(side="left")
        clabel(af, tr("Gửi lại"), lambda: self.resend(j), SEL, ACC, TKF(8, "bold")).pack(side="left", padx=3)
        clabel(af, tr("Xóa"), lambda: self.delete_one(j), RED_SOFT, RED, TKF(8, "bold")).pack(side="left")
        w["sig"] = None; self.rows[j["i"]] = w; return w

    def refresh_row(self, w):
        j = w["job"]; sig = (j["st"], j["err"], j["file"], j["thumb"], j.get("acc"), len(j["refs"]), j.get("user"))
        if sig == w["sig"]: return
        n = len(j["refs"]); w["refs"].configure(text=tr('{}/{} ảnh').format(n, MAX_REFS) if n else tr("＋ Gán ảnh"), fg=ACC if n else MUTE)
        w["sig"] = sig; txt, bg, fg = BADGE[j["st"]]; w["badge"].configure(text="● " + txt, bg=bg, fg=fg)
        w["acc"].configure(text=" · ".join(x for x in (("muse ai " + j["acc"]) if j.get("acc") else "", ("👤 " + j["user"]) if j.get("user") else "") if x))
        done = j["st"] == "done" and j["file"]
        if done:
            w["res"].pack(anchor="w", pady=(4, 0)); ph = photo(j["thumb"])
            if ph: w["th"].configure(image=ph, text="", width=0, height=0); w["th"].image = ph
        else: w["res"].pack_forget()
        if j["st"] == "fail" and j["err"]: w["err"].configure(text=tr(j["err"]) + tr("  (xem chi tiết)")); w["err"].pack(anchor="w")
        else: w["err"].pack_forget()
        set_enabled(w["open"], bool(done), ACC); set_enabled(w["dl"], bool(done), ACC)

    def sync(self, force=False):
        vis = self.visible(); key = tuple(j["i"] for j in vis)
        if force or key != self.vis_key:
            for ch in self.list.winfo_children(): ch.destroy()
            self.rows.clear(); self.vis_key = key
            if not vis:
                tk.Label(self.list, text=tr("Chưa có task nào.\nNhập prompt ở bên trái rồi bấm “Thêm vào hàng đợi”."), bg=PANEL, fg=MUTE, font=TKF(10), justify="center").pack(pady=60)
            for j in vis: self.make_row(j)
        for w in self.rows.values(): self.refresh_row(w)
        m = self.mine(); c = lambda s: sum(1 for j in m if j["st"] == s)
        self.stat["all"].configure(text=str(len(m))); self.stat["queued"].configure(text=str(c("queued")))
        self.stat["done"].configure(text=str(c("done"))); self.stat["fail"].configure(text=str(c("fail")))
        self.chip.configure(text=f"{len(m)} task")
        run = S["running"] and (self.kind, self.cur_user()) in S["runs"]; n = c("run")
        self.btn_run.configure(text=tr('●  Đang chạy ({})').format(n) if run else tr("▶  Bắt đầu chạy"))
        u = clean_name(self.V["user"].get()); self.path_lbl.configure(text=tr("Lưu vào: ") + os.path.join(self.V["out"].get().strip(), u) if u else tr("Chưa nhập tên người dùng"), text_color=MUTE if u else AMB)

class AccountsPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.content, fg_color="transparent"); self.app = app; self.rows = {}
        ctk.CTkLabel(self, text=tr("WORKSPACE     /     TÀI KHOẢN"), font=FN(11, "bold"), text_color=MUTE).pack(anchor="w", padx=4, pady=(8, 0))
        ctk.CTkLabel(self, text=tr("Tài khoản"), font=FN(24, "bold"), text_color=INK).pack(anchor="w", padx=4, pady=(10, 12))
        c1 = ctk.CTkFrame(self, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14); c1.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(c1, text=tr("Link trang tạo video / ảnh của Muse"), font=FN(13, "bold"), text_color=INK).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(c1, text=tr("Dán link trang có ô nhập prompt. Mỗi việc sẽ mở link này trong một tab mới nên kết quả không bị lẫn nhau."), font=FN(11), text_color=MUTE).pack(anchor="w", padx=16)
        ctk.CTkEntry(c1, textvariable=app.V["url"], placeholder_text="https://...", height=36, corner_radius=8, fg_color=PANEL2, border_color=LINE, text_color=INK).pack(fill="x", padx=16, pady=(8, 14))
        self.card = ctk.CTkFrame(self, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14); self.card.pack(fill="both", expand=True)
        h = ctk.CTkFrame(self.card, fg_color="transparent"); h.pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(h, text=tr("Tài khoản Muse"), font=FN(14, "bold"), text_color=INK).pack(side="left")
        ctk.CTkButton(h, text=tr("＋  Thêm tài khoản"), height=32, corner_radius=8, font=FN(12, "bold"), fg_color=ACC, hover_color=ACC_H, text_color=ACC_TXT, command=self.add).pack(side="right")
        ctk.CTkLabel(self.card, text=tr("Mỗi tài khoản có hồ sơ trình duyệt riêng. Đăng nhập một lần; sau đó tool tự chạy (ngầm hoặc hiện cửa sổ, chỉnh ở Cài đặt). Các tài khoản đang bật sẽ chia nhau hàng đợi."),
                     font=FN(11), text_color=MUTE, wraplength=760, justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        self.box = ctk.CTkFrame(self.card, fg_color="transparent"); self.box.pack(fill="x", padx=12, pady=(0, 12)); self.build()

    def build(self):
        for ch in self.box.winfo_children(): ch.destroy()
        self.rows.clear()
        for a in ST["accounts"]:
            fr = ctk.CTkFrame(self.box, fg_color=PANEL2, corner_radius=10); fr.pack(fill="x", pady=4)
            ctk.CTkLabel(fr, text="muse ai " + a["name"], font=FN(13, "bold"), text_color=INK, width=140, anchor="w").pack(side="left", padx=(14, 6), pady=14)
            st = ctk.CTkLabel(fr, text="", font=FN(12), width=260, anchor="w"); st.pack(side="left")
            ctk.CTkButton(fr, text=tr("Xóa"), width=60, height=30, fg_color=RED_SOFT, hover_color=RED_H, text_color=RED, font=FN(12, "bold"), command=lambda a=a: self.remove(a)).pack(side="right", padx=(4, 12))
            ctk.CTkButton(fr, text=tr("Đóng trình duyệt"), width=130, height=30, fg_color=LINE, hover_color=HOVER, text_color=INK, font=FN(12, "bold"), command=lambda a=a: self.close_browser(a)).pack(side="right", padx=4)
            ctk.CTkButton(fr, text=tr("Đăng nhập (mở Chrome)"), width=170, height=30, fg_color=SEL, hover_color=SEL_H, text_color=ACC, font=FN(12, "bold"), command=lambda a=a: self.login(a)).pack(side="right", padx=4)
            sw = ctk.CTkSwitch(fr, text=tr("Bật"), progress_color=ACC, text_color=INK, width=60, command=lambda a=a: self.toggle(a)); sw.pack(side="right", padx=10)
            (sw.select if a.get("on", True) else sw.deselect)(); a["_sw"] = sw
            self.rows[a["name"]] = st

    def status(self, a):
        w = WORKERS.get(a["name"])
        if w and w.state == "running":
            n = sum(1 for j in JOBS if j["st"] == "run" and j.get("acc") == a["name"]); return tr('● Đang chạy · {} luồng').format(n), ACC
        if w and w.ctx is not None and not w.closed and w.visible: return tr("● Đang mở Chrome để đăng nhập"), AMB
        if os.path.isdir(a["profile"]): return tr("● Đã có hồ sơ đăng nhập"), ACC
        return tr("● Chưa đăng nhập"), AMB
    def refresh(self):
        for a in ST["accounts"]:
            lb = self.rows.get(a["name"])
            if lb: t, col = self.status(a); lb.configure(text=t, text_color=col)
    def toggle(self, a): a["on"] = bool(a["_sw"].get())
    def login(self, a):
        url = self.app.V["url"].get().strip()
        if not url: return messagebox.showinfo(tr("Thiếu link"), tr("Hãy dán link trang Muse ở ô phía trên."))
        w = get_worker(a)
        if w.state != "idle": return messagebox.showinfo(tr("Đang chạy"), tr("Tài khoản này đang chạy việc. Hãy dừng trước khi mở Chrome để đăng nhập."))
        w.q.put(("login", url))
    def close_browser(self, a):
        w = WORKERS.get(a["name"])
        if w and w.state == "idle": w.q.put(("close", None))
    def add(self):
        name = ctk.CTkInputDialog(text=tr("Tên tài khoản mới (vd: acc2):"), title=tr("Thêm tài khoản")).get_input()
        name = re.sub(r'[\\/:*?"<>|]', "", (name or "")).strip()
        if not name: return
        if any(a["name"] == name for a in ST["accounts"]): return messagebox.showinfo(tr("Trùng tên"), tr("Đã có tài khoản tên này."))
        ST["accounts"].append({"name": name, "profile": os.path.join(PROFILES, name), "on": True}); self.build()
    def remove(self, a):
        if S["running"]: return messagebox.showinfo(tr("Đang chạy"), tr("Hãy dừng việc đang chạy trước khi xóa tài khoản."))
        if len(ST["accounts"]) <= 1: return messagebox.showinfo(tr("Không xóa được"), tr("Cần giữ ít nhất một tài khoản."))
        if not messagebox.askyesno(tr("Xóa tài khoản"), tr('Xóa tài khoản {}? (Thư mục hồ sơ đăng nhập vẫn được giữ trên máy)').format(a['name'])): return
        w = WORKERS.pop(a["name"], None)
        if w: w.q.put(("exit", None))
        ST["accounts"].remove(a); self.build()

class VaultPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.content, fg_color="transparent"); self.app = app; self.flt = ctk.StringVar(value=tr("Tất cả"))
        ctk.CTkLabel(self, text=tr("WORKSPACE     /     KHO THÀNH PHẨM"), font=FN(11, "bold"), text_color=MUTE).pack(anchor="w", padx=4, pady=(8, 0))
        hd = ctk.CTkFrame(self, fg_color="transparent"); hd.pack(fill="x", pady=(10, 12))
        ctk.CTkLabel(hd, text=tr("Kho thành phẩm"), font=FN(24, "bold"), text_color=INK).pack(side="left", padx=4)
        b = dict(height=34, corner_radius=8, font=FN(12, "bold"))
        ctk.CTkButton(hd, text=tr("📂  Mở thư mục"), fg_color=PANEL2, hover_color=LINE, text_color=INK, command=lambda: os.path.isdir(self.folder()) and open_path(self.folder()), **b).pack(side="right")
        ctk.CTkButton(hd, text=tr("↻  Làm mới"), fg_color=SEL, hover_color=SEL_H, text_color=ACC, command=self.load, **b).pack(side="right", padx=8)
        ctk.CTkOptionMenu(hd, values=[tr("Tất cả"), "Video", tr("Ảnh")], variable=self.flt, width=110, height=34, fg_color=PANEL2, button_color=LINE, dropdown_fg_color=PANEL2, text_color=INK, dropdown_text_color=INK, command=lambda v: self.load()).pack(side="right")
        self.info = ctk.CTkLabel(self, text="", font=FN(12), text_color=MUTE); self.info.pack(anchor="w", padx=4)
        self.list = ctk.CTkScrollableFrame(self, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14, scrollbar_button_color=LINE); self.list.pack(fill="both", expand=True, pady=(6, 0))
    def folder(self):
        d = self.app.V["out"].get().strip(); u = clean_name(self.app.V["user"].get())
        return os.path.join(d, u) if u else d
    def load(self):
        for ch in self.list.winfo_children(): ch.destroy()
        d = self.folder(); files = []
        try:
            for e in os.scandir(d):
                x = os.path.splitext(e.name)[1].lower()
                if e.is_file() and x in VID_EXT + IMG_EXT and (self.flt.get() == tr("Tất cả") or (self.flt.get() == "Video") == (x in VID_EXT)): files.append((e.stat().st_mtime, e.stat().st_size, e.path))
        except Exception: pass
        files.sort(reverse=True); self.info.configure(text=tr('{} tệp trong {}').format(len(files), d) + (tr(" (hiện 120 tệp mới nhất)") if len(files) > 120 else ""))
        if not files: tk.Label(self.list, text=tr("Chưa có thành phẩm nào trong thư mục này."), bg=PANEL, fg=MUTE, font=TKF(10)).pack(pady=50)
        for mt, sz, p in files[:120]:
            fr = tk.Frame(self.list, bg=PANEL); fr.pack(fill="x", pady=4, padx=6)
            isv = p.lower().endswith(VID_EXT); tp = thumb_path_for(p) if isv else p; ph = photo(tp, (64, 48))
            th = tk.Label(fr, bg=PANEL2, fg=MUTE, text="" if ph else ("🎬" if isv else "🖼"), width=9, height=3); th.pack(side="left")
            if ph: th.configure(image=ph, width=0, height=0); th.image = ph
            tk.Label(fr, text=os.path.basename(p), bg=PANEL, fg=INK, font=TKF(10, "bold"), width=34, anchor="w").pack(side="left", padx=10)
            tk.Label(fr, text=f"{sz / 1048576:.1f} MB · {time.strftime('%d/%m %H:%M', time.localtime(mt))}", bg=PANEL, fg=MUTE, font=TKF(9)).pack(side="left")
            clabel(fr, tr("Thư mục"), lambda p=p: open_path(os.path.dirname(p)), PANEL2, INK).pack(side="right", padx=4)
            clabel(fr, tr("▶ Mở") if isv else tr("🖼 Mở"), lambda p=p: open_path(p), SEL, ACC).pack(side="right", padx=4)
            tk.Frame(self.list, bg=LINE, height=1).pack(fill="x", padx=6)

class LogPage(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app.content, fg_color="transparent"); self.app = app; self.seen = 0
        ctk.CTkLabel(self, text=tr("WORKSPACE     /     NHẬT KÝ"), font=FN(11, "bold"), text_color=MUTE).pack(anchor="w", padx=4, pady=(8, 0))
        hd = ctk.CTkFrame(self, fg_color="transparent"); hd.pack(fill="x", pady=(10, 12))
        ctk.CTkLabel(hd, text=tr("Nhật ký"), font=FN(24, "bold"), text_color=INK).pack(side="left", padx=4)
        self.chip = ctk.CTkLabel(hd, text=tr("0 lỗi"), font=FN(11, "bold"), fg_color=OK_SOFT, text_color=ACC, corner_radius=12, width=70, height=26); self.chip.pack(side="left", padx=10)
        b = dict(height=34, corner_radius=8, font=FN(12, "bold"), fg_color=PANEL2, hover_color=LINE, text_color=INK)
        ctk.CTkButton(hd, text="📄 error.log", command=lambda: os.path.exists(ERR_FILE) and open_path(ERR_FILE), **b).pack(side="right")
        ctk.CTkButton(hd, text=tr("🗂 Thư mục debug"), command=lambda: open_path(DEBUG) if os.path.isdir(DEBUG) else None, **b).pack(side="right", padx=8)
        ctk.CTkButton(hd, text=tr("Xóa"), width=60, command=self.clear, **b).pack(side="right")
        ctk.CTkButton(hd, text=tr("📋 Sao chép"), command=self.copy, **b).pack(side="right", padx=8)
        self.box = ctk.CTkTextbox(self, fg_color=PANEL, border_color=LINE, border_width=1, text_color=INK, font=ctk.CTkFont(family="Consolas", size=12), wrap="word", corner_radius=14)
        self.box.pack(fill="both", expand=True); self.box.configure(state="disabled")
        for t, c in LOGC.items(): self.box._textbox.tag_config(t, foreground=c)
    def pump(self):
        errs = sum(1 for _, l, _ in LOG if l == "err"); self.chip.configure(text=tr('{} lỗi').format(errs), fg_color=RED_SOFT if errs else OK_SOFT, text_color=RED if errs else ACC)
        new = LOG[self.seen:]
        if not new: return
        self.box.configure(state="normal")
        for t, lv, tx in new: self.box.insert("end", f"[{t}] ", "info"); self.box.insert("end", tx + "\n", lv)
        self.box.configure(state="disabled"); self.box.see("end"); self.seen = len(LOG)
    def copy(self): self.app.root.clipboard_clear(); self.app.root.clipboard_append("\n".join(f"[{t}] {x}" for t, _, x in LOG))
    def clear(self):
        LOG.clear(); self.seen = 0; self.box.configure(state="normal"); self.box.delete("1.0", "end"); self.box.configure(state="disabled"); self.pump()

def fold(s):
    """Bỏ dấu tiếng Việt + chữ thường, để tìm 'giao dien' vẫn ra 'Giao diện'."""
    s = unicodedata.normalize("NFD", str(s or "").lower().replace("đ", "d"))
    return "".join(c for c in s if not unicodedata.combining(c))

RUN_KEY, RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "MuseStudio"
def autostart_cmd():
    if FROZEN: return f'"{sys.executable}"'
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"): exe = exe[:-10] + "pythonw.exe"
    return f'"{exe}" "{os.path.abspath(__file__)}"'
def autostart_get():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k: return bool(winreg.QueryValueEx(k, RUN_NAME)[0])
    except Exception: return False
def autostart_set(on):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on: winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_cmd())
            else:
                try: winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError: pass
        return True
    except Exception: return False

class SettingsPage(ctk.CTkFrame):
    """Trang Cài đặt kiểu Cốc Cốc: menu danh mục bên trái, ô tìm kiếm trên cùng, các mục dạng thẻ bên phải."""
    CATS = [("general", tr("Chung"), "⚙"), ("muse", tr("Giao diện Muse"), "▣"), ("prompt", tr("Lời nhắc (prompt)"), "✎"), ("reset", tr("Đặt lại"), "↺")]
    # (danh mục, nhóm, loại, khóa, tiêu đề, mô tả, [chữ nút])   loại: switch | entry | wide | button
    ROWS = [
        ("general", tr("Giao diện"), "choice", "theme", tr("Chủ đề"), tr("Tối, Sáng hoặc theo chế độ của Windows. Cần khởi động lại app để áp dụng.")),
        ("general", tr("Giao diện"), "choice", "lang", tr("Ngôn ngữ"), tr("Tiếng Việt hoặc English. Cần khởi động lại app để áp dụng.")),
        ("general", tr("Trình duyệt tự động"), "switch", "headless", tr("Chạy ngầm"), tr("Không hiện cửa sổ Chrome khi tool đang làm việc.")),
        ("general", tr("Trình duyệt tự động"), "entry", "delay", tr("Nghỉ giữa các lần mở việc (giây)"), tr("Giãn cách khi một tài khoản mở nhiều tab liên tiếp.")),
        ("general", tr("Khi khởi động"), "switch", "autostart", tr("Tự khởi động cùng Windows"), tr("Tự mở Muse Studio khi bạn đăng nhập máy tính. Nếu sau này di chuyển file .pyw, hãy tắt rồi bật lại mục này.")),
        ("general", tr("Dữ liệu ứng dụng"), "button", "open_data", tr("Thư mục dữ liệu"), tr("Chứa cài đặt, hồ sơ đăng nhập, ảnh chụp debug và hàng đợi."), tr("Mở")),
        ("general", tr("Dữ liệu ứng dụng"), "button", "open_log", tr("Tệp nhật ký lỗi (error.log)"), tr("Gửi tệp này cho người hỗ trợ khi tool gặp lỗi."), tr("Mở")),
        ("muse", tr("Ô nhập và nút bấm"), "entry", "ps", tr("Ô nhập prompt (CSS)"), tr("Mặc định: textarea")),
        ("muse", tr("Ô nhập và nút bấm"), "entry", "send", tr("Nút gửi (CSS)"), tr("Để trống = nhấn Enter")),
        ("muse", tr("Ô nhập và nút bấm"), "entry", "att", tr("Nút đính kèm ảnh (CSS)"), tr("Tùy chọn; tool tự dò nếu để trống")),
        ("muse", tr("Ô nhập và nút bấm"), "entry", "nc", tr("Nút 'chat mới' (CSS)"), tr("Tùy chọn")),
        ("muse", tr("Nhận kết quả"), "entry", "rs", tr("Vùng chứa kết quả (CSS)"), tr("Tùy chọn")),
        ("muse", tr("Nhận kết quả"), "entry", "mw", tr("Chỉ lấy video/ảnh rộng tối thiểu (px)"), tr("Bỏ qua ảnh nhỏ như icon")),
        ("muse", tr("Nhận kết quả"), "entry", "busy", tr("Chữ báo đang tạo"), tr("Muse hiện chữ này khi đang tạo (vd: Generating)")),
        ("muse", tr("Nhận kết quả"), "entry", "mk2", tr("Dung lượng video tối thiểu khi bắt qua mạng (KB)"), tr("Lọc bớt các tệp video quá nhỏ.")),
        ("muse", tr("Nút chọn của Muse"), "entry", "dur_click", tr("Chữ trên nút chọn thời lượng"), tr("Tùy chọn, vd: {dur}s - tool sẽ bấm vào chữ này trước khi gửi")),
        ("muse", tr("Nút chọn của Muse"), "entry", "ratio_click", tr("Chữ trên nút chọn khung hình"), tr("Tùy chọn, vd: {ratio}")),
        ("prompt", tr("Chữ đứng trước prompt"), "wide", "pfx_img", tr("Khi tạo ảnh"), ""),
        ("prompt", tr("Chữ đứng trước prompt"), "wide", "pfx_i2v", tr("Khi có ảnh tham chiếu"), ""),
        ("prompt", tr("Thông số tự thêm vào prompt"), "wide", "spec_video", tr("Prompt video"), tr("Dùng {dur} và {ratio}. Để trống nếu Muse đã có nút chọn riêng.")),
        ("prompt", tr("Thông số tự thêm vào prompt"), "wide", "spec_image", tr("Prompt ảnh"), tr("Dùng {ratio}. Để trống để tắt.")),
        ("reset", tr("Đặt lại và dọn dẹp"), "button", "reset_all", tr("Khôi phục cài đặt về mặc định"), tr("Đưa mọi mục trong Cài đặt về giá trị ban đầu. Tài khoản, hàng đợi và thư mục thành phẩm được giữ nguyên."), tr("Đặt lại")),
    ]

    def __init__(self, app):
        super().__init__(app.content, fg_color="transparent")
        self.app = app; self.vars = {}; self.switches = {}; self.cat = "general"; self.cards = {}; self.applied = (ST.get("theme", "Tối"), ST.get("lang", "Tiếng Việt"))
        self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(1, weight=1)
        # --- thanh trên: tiêu đề + ô tìm kiếm ---
        top = ctk.CTkFrame(self, fg_color="transparent"); top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(8, 12)); top.grid_columnconfigure(0, weight=1)
        hd = ctk.CTkFrame(top, fg_color="transparent"); hd.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(hd, text=tr("WORKSPACE     /     CÀI ĐẶT"), font=FN(11, "bold"), text_color=MUTE).pack(anchor="w", padx=4)
        ctk.CTkLabel(hd, text=tr("Cài đặt"), font=FN(24, "bold"), text_color=INK).pack(anchor="w", padx=4, pady=(8, 0))
        self.search = ctk.CTkEntry(top, placeholder_text=tr("⌕   Tìm kiếm trong cài đặt  (Ctrl+F)"), width=400, height=40, corner_radius=20,
                                   fg_color=PANEL, border_color=LINE, text_color=INK, font=FN(13))
        self.search.grid(row=0, column=1, sticky="e", padx=(0, 4))
        self.search.bind("<KeyRelease>", lambda e: self.render())
        self.search.bind("<Escape>", lambda e: (self.search.delete(0, "end"), self.render()))
        app.root.bind("<Control-f>", self.focus_search)
        # --- menu danh mục bên trái ---
        nav = ctk.CTkFrame(self, width=230, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14)
        nav.grid(row=1, column=0, sticky="ns", padx=(0, 16), pady=(0, 6)); nav.pack_propagate(False)
        self.navb = {}
        for i, (c, name, ic) in enumerate(self.CATS):
            b = ctk.CTkButton(nav, text=f"  {ic}   {name}", anchor="w", height=42, corner_radius=10, font=FN(13, "bold"), fg_color="transparent",
                              hover_color=PANEL2, text_color=INK, command=lambda c=c: self.set_cat(c))
            b.pack(fill="x", padx=10, pady=(12 if i == 0 else 2, 2)); self.navb[c] = b
        # --- vùng nội dung bên phải ---
        self.area = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=LINE); self.area.grid(row=1, column=1, sticky="nsew")
        self.cat_titles = {c: ctk.CTkLabel(self.area, text=f"{ic}   {name}".upper(), font=FN(11, "bold"), text_color=ACC, anchor="w") for c, name, ic in self.CATS}
        self.empty = ctk.CTkLabel(self.area, text="", font=FN(14), text_color=MUTE, justify="center")
        catname = {c: n for c, n, _ in self.CATS}
        for r in self.ROWS:
            g = self.cards.get((r[0], r[1]))
            if g is None:
                g = self.cards[(r[0], r[1])] = {"title": ctk.CTkLabel(self.area, text=r[1], font=FN(14, "bold"), text_color=INK, anchor="w"),
                                                "card": ctk.CTkFrame(self.area, fg_color=PANEL, border_color=LINE, border_width=1, corner_radius=14), "rows": []}
            g["rows"].append(self.build_row(g["card"], r, catname[r[0]]))
        self.hl = self.switches.get("headless")
        self.render()

    def build_row(self, card, r, catname):
        cat, grp, kind, key, label, hint = r[:6]
        row = ctk.CTkFrame(card, fg_color="transparent"); row.grid_columnconfigure(0, weight=1)
        sep = ctk.CTkFrame(card, height=1, fg_color=LINE)
        wide = kind == "wide"; wrap = 700 if wide else (420 if kind in ("entry", "choice") else 520)
        txt = ctk.CTkFrame(row, fg_color="transparent"); txt.grid(row=0, column=0, sticky="w", padx=(18, 12), pady=(12, 6 if wide else 12))
        ctk.CTkLabel(txt, text=label, font=FN(13, "bold"), text_color=INK, anchor="w", justify="left", wraplength=wrap).pack(anchor="w")
        if hint: ctk.CTkLabel(txt, text=hint, font=FN(11), text_color=MUTE, anchor="w", justify="left", wraplength=wrap).pack(anchor="w", pady=(2, 0))
        if kind == "switch":
            sw = ctk.CTkSwitch(row, text="", width=46, progress_color=ACC, command=lambda k=key: self.toggle(k)); sw.grid(row=0, column=1, padx=18)
            (sw.select if (autostart_get() if key == "autostart" else ST.get(key, DEF[key])) else sw.deselect)(); self.switches[key] = sw
        elif kind == "choice":
            v = ctk.StringVar(value=choice_label(key, str(ST.get(key, DEF[key])))); self.vars[key] = v
            ctk.CTkOptionMenu(row, values=[choice_label(key, o) for o in CHOICES[key]], variable=v, width=170, height=34, corner_radius=8, font=FN(12, "bold"), fg_color=PANEL2, button_color=LINE,
                              button_hover_color=HOVER, dropdown_fg_color=PANEL2, dropdown_text_color=INK, dropdown_hover_color=LINE, text_color=INK,
                              command=lambda val: (self.save(), self.restart_check())).grid(row=0, column=1, padx=18)
        elif kind in ("entry", "wide"):
            v = ctk.StringVar(value=str(ST.get(key, DEF[key]))); self.vars[key] = v
            e = ctk.CTkEntry(row, textvariable=v, height=34, corner_radius=8, fg_color=PANEL2, border_color=LINE, text_color=INK, **({} if wide else {"width": 300}))
            if wide: e.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 14))
            else: e.grid(row=0, column=1, padx=18)
            e.bind("<FocusOut>", lambda ev: self.save()); e.bind("<Return>", lambda ev: self.save())
        elif kind == "button":
            ctk.CTkButton(row, text=r[6], width=110, height=34, corner_radius=8, fg_color=PANEL2, hover_color=LINE, text_color=INK, font=FN(12, "bold"),
                          command=lambda k=key: self.act(k)).grid(row=0, column=1, padx=18)
        return {"row": row, "sep": sep, "hay": fold(" ".join((catname, grp, label, hint, key)))}

    def render(self):
        terms = fold(self.search.get()).split()
        for w in self.cat_titles.values(): w.pack_forget()
        self.empty.pack_forget()
        for g in self.cards.values():
            g["title"].pack_forget(); g["card"].pack_forget()
            for r in g["rows"]: r["row"].pack_forget(); r["sep"].pack_forget()
        shown = 0
        for cat, name, ic in self.CATS:
            if not terms and cat != self.cat: continue
            blocks = [(g, [r for r in g["rows"] if all(t in r["hay"] for t in terms)]) for k, g in self.cards.items() if k[0] == cat]
            blocks = [(g, vis) for g, vis in blocks if vis]
            if not blocks: continue
            if terms: self.cat_titles[cat].pack(anchor="w", padx=4, pady=(16, 0))
            for g, vis in blocks:
                g["title"].pack(anchor="w", padx=6, pady=(14, 8)); g["card"].pack(fill="x", padx=(0, 6)); shown += 1
                for i, r in enumerate(vis):
                    if i: r["sep"].pack(fill="x", padx=18)
                    r["row"].pack(fill="x")
        if not shown:
            self.empty.configure(text=tr('Không tìm thấy cài đặt nào khớp với “{}”.\nThử từ khóa khác, ví dụ: ngầm, prompt, nút gửi.').format(self.search.get().strip())); self.empty.pack(pady=70)
        for c, b in self.navb.items():
            on = c == self.cat and not terms
            b.configure(fg_color=SEL if on else "transparent", text_color=ACC if on else INK)

    def set_cat(self, c):
        self.search.delete(0, "end"); self.cat = c; self.render()
        try: self.area._parent_canvas.yview_moveto(0)
        except Exception: pass

    def focus_search(self, e=None):
        if self.app.cur == "set": self.search.focus_set(); self.search.select_range(0, "end")

    def act(self, key):
        if key == "open_data": open_path(DATA)
        elif key == "open_log":
            if os.path.exists(ERR_FILE): open_path(ERR_FILE)
            else: messagebox.showinfo(tr("Chưa có nhật ký lỗi"), tr("Tool chưa ghi lỗi nào ra tệp error.log."))
        elif key == "reset_all": self.reset(confirm=True)

    def toggle(self, k):
        if k != "autostart": return self.save()
        sw = self.switches[k]
        if not autostart_set(bool(sw.get())):
            (sw.deselect if sw.get() else sw.select)()
            messagebox.showinfo(tr("Không thực hiện được"), tr("Không ghi được vào Windows (tính năng này chỉ có trên Windows, hoặc bị chặn quyền)."))

    def restart_check(self):
        if (ST.get("theme", "Tối"), ST.get("lang", "Tiếng Việt")) == self.applied: return
        if S["running"]: return messagebox.showinfo(tr("Cần khởi động lại"), tr("Đang có việc chạy nên chưa khởi động lại. Thay đổi sẽ áp dụng ở lần mở app sau."))
        if messagebox.askyesno(tr("Khởi động lại để áp dụng"), tr("Cần khởi động lại Muse Studio để áp dụng chủ đề hoặc ngôn ngữ mới.\nKhởi động lại ngay?")):
            self.app.sync_cfg(); save_tasks()
            try: subprocess.Popen([sys.executable] if FROZEN else [sys.executable, os.path.abspath(__file__)], cwd=BASE)
            finally: os._exit(0)

    def save(self):
        for k, sw in self.switches.items():
            if k in DEF: ST[k] = bool(sw.get())
        for k, v in self.vars.items(): ST[k] = choice_value(k, v.get()) if k in CHOICES else v.get()
        save_settings()

    def reset(self, confirm=False):
        if confirm and not messagebox.askyesno(tr("Khôi phục mặc định"), tr("Đưa tất cả mục trong Cài đặt về giá trị mặc định?\n(Tài khoản, hàng đợi và thư mục thành phẩm không bị ảnh hưởng.)")): return
        for k, v in self.vars.items(): v.set(choice_label(k, str(DEF[k])) if k in CHOICES else str(DEF[k]))
        for k, sw in self.switches.items():
            if k in DEF: (sw.select if DEF[k] else sw.deselect)()
        self.save(); self.restart_check()


NAV = [("video", "▣", tr("Tạo video")), ("image", "▨", tr("Tạo ảnh")), ("acc", "☻", tr("Tài khoản")), ("vault", "▤", tr("Kho thành phẩm")), ("log", "≡", tr("Nhật ký")), ("set", "⚙", tr("Cài đặt"))]

class App:
    def __init__(self):
        ctk.set_appearance_mode(THEME)
        self.root = root = ctk.CTk(fg_color=BG); root.title(tr("Muse Studio - Tạo video hàng loạt")); root.geometry("1600x920"); root.minsize(1280, 700)
        root.grid_columnconfigure(0, weight=1); root.grid_rowconfigure(0, weight=1)
        self.V = {k: ctk.StringVar(value=str(ST.get(k, DEF[k]))) for k in ("url", "user", "out", "threads", "wait_min")}
        self.content = ctk.CTkFrame(root, fg_color="transparent"); self.content.grid(row=0, column=0, sticky="nsew", padx=(20, 12), pady=(10, 14))
        self.content.grid_columnconfigure(0, weight=1); self.content.grid_rowconfigure(0, weight=1)
        self.pages = {"video": CreatePage(self, "video"), "image": CreatePage(self, "image"), "acc": AccountsPage(self), "vault": VaultPage(self), "log": LogPage(self), "set": SettingsPage(self)}
        side = ctk.CTkFrame(root, width=220, fg_color=BG, corner_radius=0, border_width=0); side.grid(row=0, column=1, sticky="ns", padx=(0, 14)); side.pack_propagate(False)
        try:
            ico = res_path("muse_studio.ico")
            if os.path.exists(ico) and sys.platform.startswith("win"): root.iconbitmap(ico)
        except Exception: pass
        lg = None
        try:
            if HAVE_PIL and os.path.exists(res_path("muse_logo.png")):
                lg = ctk.CTkImage(Image.open(res_path("muse_logo.png")), size=(56, 56))
        except Exception: lg = None
        if lg:
            lr = ctk.CTkFrame(side, fg_color="transparent"); lr.pack(anchor="w", padx=14, pady=(24, 0))
            ctk.CTkLabel(lr, text="", image=lg).pack(side="left")
            ctk.CTkLabel(lr, text="Muse Studio", font=FN(15, "bold"), text_color=INK).pack(side="left", padx=10)
        ctk.CTkLabel(side, text="WORKSPACE", font=FN(10, "bold"), text_color=MUTE).pack(anchor="w", padx=18, pady=((22 if lg else 60), 10))
        self.navb = {}
        for k, ic, t in NAV:
            b = ctk.CTkButton(side, text=f"  {ic}   {t}", anchor="w", height=44, corner_radius=10, font=FN(13, "bold"), fg_color="transparent", hover_color=PANEL2, text_color=INK, command=lambda k=k: self.show(k))
            b.pack(fill="x", padx=10, pady=2); self.navb[k] = b
        ctk.CTkLabel(side, text=f"v{VERSION}", font=FN(10), text_color=MUTE).pack(side="bottom", anchor="w", padx=18, pady=14)
        self.upd_ready = None; self.upd_asked = False
        if FROZEN and UPDATE_URL.strip(): threading.Thread(target=self.check_update, daemon=True).start()
        self.cur = None; self.show("video"); self.tick = 0
        root.bind("<Control-Return>", lambda e: self.start_run(self.cur if self.cur in ("video", "image") else "video"))
        root.protocol("WM_DELETE_WINDOW", self.close); self.refresh()

    def check_update(self):
        """Chạy nền khi mở app: so sánh version.json trên mạng với bản đang dùng, tải mã mới về nếu có."""
        import urllib.request
        try:
            def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "MuseStudio"}), timeout=15).read()
            info = json.loads(get(UPDATE_URL.strip() + ("&" if "?" in UPDATE_URL else "?") + "t=" + str(int(time.time()))).decode("utf-8-sig"))
            ver, url = str(info.get("version", "")), str(info.get("url", "")).strip()
            if not ver or not url or _ver(ver) <= _ver(VERSION): return
            if os.path.exists(_UPD_FILE):
                m = re.search(r'^VERSION\s*=\s*"([\d.]+)"', open(_UPD_FILE, encoding="utf-8").read(), re.M)
                if m and _ver(m.group(1)) >= _ver(ver): self.upd_ready = ver; return
            data = get(url)
            sha = str(info.get("sha256", "")).strip().lower()
            if sha and hashlib.sha256(data).hexdigest() != sha: raise Exception("sha256 không khớp")
            src = data.decode("utf-8-sig"); compile(src, "muse_studio.py", "exec")        # kiểm tra cú pháp trước khi nhận
            if not re.search(r'^VERSION\s*=\s*"' + re.escape(ver) + '"', src, re.M): raise Exception("VERSION trong tệp không khớp version.json")
            os.makedirs(_UPD_DIR, exist_ok=True); tmp = _UPD_FILE + ".part"
            open(tmp, "wb").write(src.encode("utf-8")); os.replace(tmp, _UPD_FILE)
            elog("ok", tr("Đã tải bản cập nhật {}").format(ver)); self.upd_ready = ver
        except Exception as e:
            elog("info", "Update check: " + first_line(e))

    def offer_restart(self):
        self.upd_asked = True
        if S["running"]: return messagebox.showinfo(tr("Có bản cập nhật"), tr("Đang chạy việc nên chưa khởi động lại. Bản mới sẽ được dùng ở lần mở app sau."))
        if messagebox.askyesno(tr("Có bản cập nhật"), tr("Có bản cập nhật mới ({}).\nKhởi động lại Muse Studio để dùng ngay?").format(self.upd_ready)):
            self.sync_cfg(); save_tasks()
            try: subprocess.Popen([sys.executable], cwd=BASE)
            finally: os._exit(0)

    def show(self, k):
        for n, p in self.pages.items():
            if n == k: p.grid(row=0, column=0, sticky="nsew")
            else: p.grid_remove()
        for n, b in self.navb.items(): b.configure(fg_color=SEL if n == k else "transparent", text_color=ACC if n == k else INK)
        self.cur = k
        if k == "vault": self.pages["vault"].load()
        if k in ("video", "image"): self.pages[k].sync(True)

    def sync_cfg(self):
        for k, v in self.V.items(): ST[k] = v.get()
        for k in ("video", "image"): self.pages[k].persist()
        self.pages["set"].save()

    def start_run(self, kind, quiet=False, user=None):
        user = clean_name(self.V["user"].get()) if user is None else user
        with LOCK:
            if not any(j["st"] == "queued" and j["kind"] == kind and j.get("user", "") == user for j in JOBS):
                return None if quiet else messagebox.showinfo(tr("Hàng đợi trống"), tr("Chưa có task nào đang chờ của người dùng này. Hãy thêm prompt vào hàng đợi trước."))
        if not self.V["url"].get().strip(): return messagebox.showinfo(tr("Thiếu link"), tr("Vào mục Tài khoản và dán link trang Muse trước."))
        usable = [a for a in ST["accounts"] if a.get("on", True) and os.path.isdir(a["profile"])]
        if not usable: return messagebox.showinfo(tr("Chưa đăng nhập"), tr("Chưa có tài khoản nào được bật và đã đăng nhập.\nVào mục Tài khoản, bấm 'Đăng nhập (mở Chrome)' rồi đăng nhập Muse."))
        self.sync_cfg(); cfg = build_cfg(self.V)
        with LOCK: S["stop"] = False; S["running"] = True; S["runs"].add((kind, user))
        elog("info", tr("Bắt đầu chạy {} của '{}': {} tài khoản x {} luồng ({}).").format(kind, tr(user or 'không tên'), len(usable), cfg['threads'], tr('chạy ngầm' if cfg['headless'] else 'hiện cửa sổ')))
        for a in usable:
            w = get_worker(a)
            if w.state == "idle": w.state = "queued"; w.q.put(("run", cfg))

    def stop_all(self):
        if S["running"]: S["stop"] = True; elog("info", tr("Đã bấm Dừng tất cả."))

    def refresh(self):
        try:
            self.tick += 1
            if self.cur in ("video", "image"): self.pages[self.cur].sync()
            elif self.cur == "acc": self.pages["acc"].refresh()
            self.pages["log"].pump()
            if self.upd_ready and not self.upd_asked: self.offer_restart()
            if self.tick % 8 == 0: save_tasks()
        except Exception: log_err()
        self.root.after(1000, self.refresh)

    def close(self):
        try: self.sync_cfg(); save_settings(); save_tasks()
        finally: os._exit(0)

if __name__ == "__main__":
    app = App(); app.root.mainloop()
