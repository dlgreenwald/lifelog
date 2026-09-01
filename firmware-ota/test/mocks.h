#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>
#include <map>

// ── ESP32 types ────────────────────────────────────────────────────

typedef int32_t esp_err_t;
typedef int32_t BaseType_t;
typedef uint32_t TickType_t;
typedef void* QueueHandle_t;
typedef void* TaskHandle_t;
typedef void* SemaphoreHandle_t;

#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_INTR_FLAG_LEVEL1 0
#define ESP_ERR_TIMEOUT -1

// ── millis stub ────────────────────────────────────────────────────

static uint32_t mock_millis_value = 10000;
inline uint32_t millis() { return mock_millis_value; }
inline void delay(uint32_t ms) { mock_millis_value += ms; }

// ── FreeRTOS stubs ─────────────────────────────────────────────────

#define pdMS_TO_TICKS(x) ((x))
#define portMAX_DELAY 0xFFFFFFFF
#define pdTRUE 1
inline void vTaskDelay(TickType_t ticks) { mock_millis_value += ticks; }
inline BaseType_t xTaskNotifyTake(BaseType_t clear, TickType_t timeout) { return pdTRUE; }
inline void xTaskNotifyGive(TaskHandle_t handle) {}

// ── GPIO / LED stubs (native test) ────────────────────────────────
// LED_PIN comes from config.h via led.cpp's include chain — do not redefine.
#define HIGH 1
#define LOW 0
extern int mock_digital_write_pin;
extern int mock_digital_write_val;
extern std::vector<std::pair<int,int>> mock_digital_write_calls;
int mock_digital_write_pin = -1;
int mock_digital_write_val = -1;
std::vector<std::pair<int,int>> mock_digital_write_calls;
inline void digitalWrite(int pin, int val) {
    mock_digital_write_pin = pin;
    mock_digital_write_val = val;
    mock_digital_write_calls.push_back({pin, val});
}
// ── Recursive mutex stubs (LED preemption) ────────────────────────
extern "C" {
inline BaseType_t xSemaphoreTakeRecursive(SemaphoreHandle_t, TickType_t) { return pdTRUE; }
inline BaseType_t xSemaphoreGiveRecursive(SemaphoreHandle_t) { return pdTRUE; }
}
#define I2S_NUM_0 0
#define I2S_MODE_MASTER 1
#define I2S_MODE_RX 2
#define I2S_MODE_PDM 4
#define I2S_BITS_PER_SAMPLE_16BIT 16
#define I2S_CHANNEL_FMT_ONLY_LEFT 1
#define I2S_COMM_FORMAT_STAND_I2S 1
#define I2S_PIN_NO_CHANGE -1
#define I2S_MCLK_MULTIPLE_DEFAULT 0
#define I2S_BITS_PER_CHAN_DEFAULT 0
#define I2S_CHANNEL_MONO 1

typedef struct {
    int mode;
    int sample_rate;
    int bits_per_sample;
    int channel_format;
    int communication_format;
    int intr_alloc_flags;
    int dma_buf_count;
    int dma_buf_len;
    int use_apll;
    int tx_desc_auto_clear;
    int fixed_mclk;
    int mclk_multiple;
    int bits_per_chan;
} i2s_config_t;

typedef struct {
    int mck_io_num;
    int bck_io_num;
    int ws_io_num;
    int data_out_num;
    int data_in_num;
} i2s_pin_config_t;

inline esp_err_t i2s_driver_install(int, const i2s_config_t*, int, void*) { return ESP_OK; }
inline esp_err_t i2s_set_pin(int, const i2s_pin_config_t*) { return ESP_OK; }
inline esp_err_t i2s_set_clk(int, int, int, int) { return ESP_OK; }
inline esp_err_t i2s_read(int, void*, size_t, size_t*, TickType_t) { return ESP_OK; }

// ── Arduino String stub ────────────────────────────────────────────

class String {
    std::string s_;
    size_t read_pos_ = 0;
public:
    String() = default;
    String(const char* c) : s_(c ? c : ""), read_pos_(0) {}
    String(const std::string& s) : s_(s), read_pos_(0) {}
    String(int v) : s_(std::to_string(v)), read_pos_(0) {}
    String& operator+=(const String& o) { s_ += o.s_; return *this; }
    friend String operator+(const String& a, const String& b) { return String(a.s_ + b.s_); }
    const char* c_str() const { return s_.c_str(); }
    int indexOf(char c, int from = 0) const {
        auto pos = s_.find(c, from);
        return pos == std::string::npos ? -1 : (int)pos;
    }
    int indexOf(const char* sub, int from = 0) const {
        auto pos = s_.find(sub, from);
        return pos == std::string::npos ? -1 : (int)pos;
    }
    String substring(int from) const { return String(s_.substr(from)); }
    String substring(int from, int len) const { return String(s_.substr(from, len)); }
    bool endsWith(const char* suffix) const {
        size_t sl = strlen(suffix);
        return s_.size() >= sl && s_.compare(s_.size() - sl, sl, suffix) == 0;
    }
    void trim() {
        auto b = s_.find_first_not_of(" \t\r\n");
        auto e = s_.find_last_not_of(" \t\r\n");
        s_ = (b == std::string::npos) ? "" : s_.substr(b, e - b + 1);
    }
    int length() const { return (int)s_.size(); }
    bool operator==(const char* c) const { return s_ == c; }
    bool operator!=(const char* c) const { return s_ != c; }
    operator bool() const { return !s_.empty(); }
    // ArduinoJson compatibility
    size_t write(uint8_t c) { s_ += (char)c; return 1; }
    size_t write(const uint8_t* data, size_t len) { s_.append((const char*)data, len); return len; }
    int read() {
        if (read_pos_ >= s_.size()) return -1;
        return (unsigned char)s_[read_pos_++];
    }
    size_t available() const { return s_.size() - read_pos_; }
    String& operator+=(char c) { s_ += c; return *this; }
    String& operator+=(const char* c) { s_ += c ? c : ""; return *this; }
};

// ── Serial stub ────────────────────────────────────────────────────

struct MockSerial {
    bool available() { return false; }
    String readStringUntil(char) { return ""; }
    void print(const char*) {}
    void println(const char*) {}
    void printf(const char*, ...) {}
};
static MockSerial Serial;

inline void* ps_malloc(size_t size) { return malloc(size); }
inline void* ps_realloc(void *ptr, size_t size) { return realloc(ptr, size); }

// ── esp_heap stub ──────────────────────────────────────────────────

#define MALLOC_CAP_SPIRAM 0x10000
inline size_t heap_caps_get_free_size(int caps) {
    (void)caps;
    return 8 * 1024 * 1024;  // 8MB — plenty for tests
}

// ── esp_random stub ────────────────────────────────────────────────

inline uint32_t esp_random() { return 12345; }

// ── WiFi stub ──────────────────────────────────────────────────────

#define WL_CONNECTED 3
typedef int arduino_event_id_t;
#define ARDUINO_EVENT_WIFI_STA_CONNECTED 4
#define ARDUINO_EVENT_WIFI_STA_DISCONNECTED 5

static int mock_wifi_status = 0;  // 0 = disconnected by default
static String mock_wifi_ssid = "MockSSID";
static String mock_wifi_ip = "192.168.1.100";
static int mock_wifi_rssi = -50;
static void (*mock_wifi_event_handler)(arduino_event_id_t) = nullptr;

struct IPAddress {
    String toString() { return mock_wifi_ip; }
};

struct MockWiFi {
    int status() { return mock_wifi_status; }
    void begin(const char* ssid) {}
    void begin(const char* ssid, const char* pass) {}
    void disconnect() {}
    IPAddress localIP() { return IPAddress(); }
    String SSID() { return mock_wifi_ssid; }
    int RSSI() { return mock_wifi_rssi; }
    void onEvent(void (*handler)(arduino_event_id_t)) { mock_wifi_event_handler = handler; }
};
static MockWiFi WiFi;

// ── SD stub (File + SD) ────────────────────────────────────────────

// Captures what was written to each file
struct WrittenFile {
    std::string name;
    std::vector<uint8_t> data;
};
static std::vector<WrittenFile> mock_sd_files;
static std::string mock_sd_open_name;
static bool mock_sd_open_should_fail = false;

#define FILE_WRITE 2
#define FILE_READ 1

// Minimal File class that captures writes
class File {
    std::string name_;
    std::vector<uint8_t> buf_;
    bool open_ = false;
    size_t read_pos_ = 0;
public:
    File() = default;
    File(const std::string& n) : name_(n), open_(true) {}

    operator bool() const { return open_; }
    size_t write(const uint8_t* data, size_t len) {
        if (!open_) return 0;
        buf_.insert(buf_.end(), data, data + len);
        return len;
    }
    size_t write(uint8_t c) { return write(&c, 1); }
    void flush() {}
    void close() {
        if (open_ && !name_.empty()) {
            WrittenFile wf;
            wf.name = name_;
            wf.data = buf_;
            mock_sd_files.push_back(wf);
        }
        open_ = false;
    }
    size_t size() const { return buf_.size(); }
    const std::string& name() const { return name_; }
    bool available() { return read_pos_ < buf_.size(); }
    int read(uint8_t *dst, size_t len) {
        if (!open_) return 0;
        size_t avail = buf_.size() - read_pos_;
        size_t toRead = (len < avail) ? len : avail;
        if (toRead == 0) return 0;
        memcpy(dst, buf_.data() + read_pos_, toRead);
        read_pos_ += toRead;
        return toRead;
    }
};

struct SDClass {
    File open(const char* path, int mode = 0) {
        if (mock_sd_open_should_fail) return File();
        return File(std::string(path));
    }
    bool remove(const char*) { return true; }
    bool begin(int) { return true; }
};
static SDClass SD;  // NOLINT — intentional global

// ── Upload mock ────────────────────────────────────────────────────

struct UploadCall {
    std::string filename;
    uint32_t utteranceId;
    uint32_t chunkIndex;
    bool isFinal;
};
static std::vector<UploadCall> mock_upload_calls;
static bool mock_upload_should_succeed = true;
static std::vector<std::string> mock_uploaded_files;

inline bool uploadFile(const char* filename, uint32_t uttId, uint32_t chunkIdx, bool final) {
    UploadCall call = {std::string(filename), uttId, chunkIdx, final};
    mock_upload_calls.push_back(call);
    mock_uploaded_files.push_back(std::string(filename));
    return mock_upload_should_succeed;
}
// ── Upload from memory mock ───────────────────────────────────────
struct UploadMemCall {
    const uint8_t *data;
    uint32_t size;
    std::string filename;
    uint32_t utteranceId;
    uint32_t chunkIndex;
    bool isFinal;
};
static std::vector<UploadMemCall> mock_upload_mem_calls;

inline bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                                 const char *filename, uint32_t uttId,
                                 uint32_t chunkIdx, bool final) {
    UploadMemCall call = {data, size, std::string(filename), uttId, chunkIdx, final};
    if (size < 4096) return true;  // Short clip — discard (matches real impl)
    mock_upload_mem_calls.push_back(call);
    return mock_upload_should_succeed;
}

// ── Preferences stub ───────────────────────────────────────────────

static std::map<std::string, std::string> mock_prefs_strings;
static std::map<std::string, uint16_t> mock_prefs_ushorts;
static std::map<std::string, uint32_t> mock_prefs_uints;
static std::map<std::string, bool> mock_prefs_bools;
static std::map<std::string, uint8_t> mock_prefs_uchars;

struct Preferences {
    void begin(const char*, bool = false) {}
    void putUInt(const char* k, uint32_t v) { mock_prefs_uints[k] = v; }
    uint32_t getUInt(const char* k, uint32_t def = 0) {
        auto it = mock_prefs_uints.find(k); return it != mock_prefs_uints.end() ? it->second : def;
    }
    void putUChar(const char* k, uint8_t v) { mock_prefs_uchars[k] = v; }
    uint8_t getUChar(const char* k, uint8_t def = 0) {
        auto it = mock_prefs_uchars.find(k); return it != mock_prefs_uchars.end() ? it->second : def;
    }
    void putBool(const char* k, bool v) { mock_prefs_bools[k] = v; }
    bool getBool(const char* k, bool def = false) {
        auto it = mock_prefs_bools.find(k); return it != mock_prefs_bools.end() ? it->second : def;
    }
    void putString(const char* k, const char* v) { mock_prefs_strings[k] = v; }
    void putString(const char* k, const String& v) { mock_prefs_strings[k] = v.c_str(); }
    String getString(const char* k, const char* def = "") {
        auto it = mock_prefs_strings.find(k); return it != mock_prefs_strings.end() ? String(it->second) : String(def);
    }
    void putUShort(const char* k, uint16_t v) { mock_prefs_ushorts[k] = v; }
    uint16_t getUShort(const char* k, uint16_t def = 0) {
        auto it = mock_prefs_ushorts.find(k); return it != mock_prefs_ushorts.end() ? it->second : def;
    }
    void end() {}
};

// ── ArduinoOTA stub ────────────────────────────────────────────────

struct ArduinoOTAClass {
    void begin() {}
    void handle() {}
};
static ArduinoOTAClass ArduinoOTA;  // NOLINT — intentional global

// ── WiFiManager stub ───────────────────────────────────────────────

typedef void (*WiFiManagerSaveCallback)();

static String mock_wm_ssid = "TestSSID";
static String mock_wm_pass = "testpass";
static WiFiManagerSaveCallback mock_wm_save_cb = nullptr;
static std::vector<String> mock_wm_params;
static bool mock_wm_portal_should_connect = true;

struct WiFiManagerParameter {
    const char* _id;
    const char* _label;
    char _value[256];
    int _length;
    WiFiManagerParameter() : _id(""), _label(""), _length(0) { _value[0] = '\0'; }
    WiFiManagerParameter(const char* id, const char* label, const char* value, int length)
        : _id(id), _label(label), _length(length) {
        strlcpy(_value, value ? value : "", sizeof(_value));
    }
    const char* getValue() { return _value; }
    void setValue(const char* v) { strlcpy(_value, v, sizeof(_value)); }
};

struct WiFiManager {
    void autoConnect(const char*) {}
    void setConfigPortalTimeout(uint32_t) {}
    void setTitle(const char*) {}
    void setSaveParamsCallback(WiFiManagerSaveCallback cb) { mock_wm_save_cb = cb; }
    void addParameter(WiFiManagerParameter*) {}
    bool startConfigPortal(const char*, const char* = nullptr) { return mock_wm_portal_should_connect; }
    String getWiFiSSID() { return mock_wm_ssid; }
    String getWiFiPass() { return mock_wm_pass; }
    void setAPPassword(const char*) {}
    String ssid() { return "MockSSID"; }
    String psk() { return "mockpass"; }
};

// ── RemoteDebug stub ───────────────────────────────────────────────

struct RemoteDebug {
    void begin(const char*) {}
    void handle() {}
};

// ── ESPmDNS stub ───────────────────────────────────────────────────

struct MockMDNS {
    bool begin(const char*) { return true; }
    void addService(const char*, const char*, uint16_t) {}
};
static MockMDNS MDNS;

// ── ESPUI stub ─────────────────────────────────────────────────────

enum class Verbosity { Quiet = 0, SomeJSON = 1, VerboseJSON = 2 };

enum class ControlColor {
    Turquoise, Emerald, Peterriver, Wetasphalt, Sunflower, Carrot, Alizarin, Dark,
    None = 0xFF
};

struct MockControl {
    String value;
};

struct MockESPUI {
    std::vector<MockControl> controls;
    void setVerbosity(Verbosity) {}
    void begin(const char*) {}
    void begin(const char*, const char*, const char*) {}
    void separator(const char*) {}
    uint16_t label(const char*, ControlColor, const String& val = "") {
        controls.push_back({val}); return controls.size() - 1;
    }
    uint16_t text(const char*, void*, ControlColor, const String& val = "") {
        controls.push_back({val}); return controls.size() - 1;
    }
    uint16_t button(const char*, void*, ControlColor, const char*) {
        controls.push_back({""}); return controls.size() - 1;
    }
    MockControl* getControl(uint16_t id) {
        if (id < controls.size()) return &controls[id];
        return nullptr;
    }
    void updateLabel(uint16_t id, const String& val) {
        if (id < controls.size()) controls[id].value = val;
    }
};
static MockESPUI ESPUI;

// ── Opus stubs ─────────────────────────────────────────────────────

typedef int32_t opus_int32;
typedef int16_t opus_int16;

#define OPUS_APPLICATION_VOIP 2048
#define OPUS_APPLICATION_AUDIO 2049
#define OPUS_APPLICATION_RESTRICTED_LOWDELAY 2051
#define OPUS_OK 0
#define OPUS_SET_BITRATE(x) 0, (x)
#define OPUS_SET_COMPLEXITY(x) 0, (x)
#define OPUS_SET_SIGNAL(x) 0, (x)
#define OPUS_SIGNAL_VOICE 3001
#define OPUS_SIGNAL_MUSIC 3002
#define OPUS_AUTO 0

struct OpusEncoder { int dummy; };

inline OpusEncoder* opus_encoder_create(opus_int32 Fs, int channels, int application, int* error) {
    *error = OPUS_OK;
    return new OpusEncoder();
}

inline int opus_encoder_ctl(OpusEncoder*, ...) { return OPUS_OK; }

inline opus_int32 opus_encode(OpusEncoder*, const opus_int16*, int frame_size,
                               unsigned char* data, opus_int32 max_bytes) {
    // Stub: write a few dummy bytes to simulate encoded output
    opus_int32 len = (frame_size < max_bytes) ? frame_size : max_bytes;
    if (len > 200) len = 50;  // Simulate compression
    for (opus_int32 i = 0; i < len; i++) data[i] = (unsigned char)(i & 0xFF);
    return len;
}

inline void opus_encoder_destroy(OpusEncoder* enc) { delete enc; }

// ── OGG stubs ──────────────────────────────────────────────────────

typedef int64_t ogg_int64_t;

typedef struct {
    unsigned char *header;
    long header_len;
    unsigned char *body;
    long body_len;
} ogg_page;

typedef struct {
    unsigned char *body_data;
    long body_storage;
    long body_fill;
    long body_returned;
    int *lacing_vals;
    ogg_int64_t *granule_vals;
    long lacing_storage;
    long lacing_fill;
    long lacing_packet;
    long lacing_returned;
    unsigned char header[282];
    int header_fill;
    int e_o_s;
    int b_o_s;
    long serialno;
    long pageno;
    ogg_int64_t packetno;
    ogg_int64_t granulepos;
} ogg_stream_state;

typedef struct {
    unsigned char *packet;
    long bytes;
    long b_o_s;
    long e_o_s;
    ogg_int64_t granulepos;
    ogg_int64_t packetno;
} ogg_packet;

// Minimal OGG stream implementation for testing
struct MockOGGStream {
    long serialno = 0;
    std::vector<ogg_packet> packets;
    std::vector<ogg_page> pages;
    int page_counter = 0;
};

static std::vector<MockOGGStream> mock_ogg_streams;
static int mock_ogg_stream_idx = 0;

inline int ogg_stream_init(ogg_stream_state* os, int serialno) {
    os->serialno = serialno;
    os->pageno = 0;
    os->packetno = 0;
    os->e_o_s = 0;
    os->b_o_s = 0;
    MockOGGStream ms;
    ms.serialno = serialno;
    mock_ogg_streams.push_back(ms);
    mock_ogg_stream_idx = mock_ogg_streams.size() - 1;
    return 0;
}

inline int ogg_stream_clear(ogg_stream_state*) { return 0; }

inline int ogg_stream_reset_serialno(ogg_stream_state* os, int serialno) {
    os->serialno = serialno;
    os->pageno = 0;
    os->packetno = 0;
    return 0;
}

inline int ogg_stream_packetin(ogg_stream_state* os, ogg_packet* op) {
    os->packetno = op->packetno + 1;
    return 0;
}

inline int ogg_stream_pageout(ogg_stream_state* os, ogg_page* og) {
    // Generate a fake page for each call, then stop
    static int calls = 0;
    if (calls >= 2) { calls = 0; return 0; }
    calls++;
    og->header = (unsigned char*)malloc(4);
    memcpy(og->header, "head", 4);
    og->header_len = 4;
    og->body = (unsigned char*)malloc(4);
    memcpy(og->body, "body", 4);
    og->body_len = 4;
    os->pageno++;
    return 1;
}

inline int ogg_stream_flush(ogg_stream_state* os, ogg_page* og) {
    return ogg_stream_pageout(os, og);
}

inline void ogg_packet_clear(ogg_packet*) {}
