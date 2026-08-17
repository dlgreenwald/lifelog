#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>

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

// ── FreeRTOS stubs ─────────────────────────────────────────────────

#define pdMS_TO_TICKS(x) ((x))
#define portMAX_DELAY 0xFFFFFFFF
#define pdTRUE 1
#define pdFALSE 0

inline void vTaskDelay(TickType_t ticks) {}
inline void delay(uint32_t ms) {}
inline BaseType_t xTaskNotifyTake(BaseType_t clear, TickType_t timeout) { return pdTRUE; }
inline void xTaskNotifyGive(TaskHandle_t handle) {}

// ── I2S stubs ──────────────────────────────────────────────────────

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
public:
    String() = default;
    String(const char* c) : s_(c ? c : "") {}
    String(const std::string& s) : s_(s) {}
    String(int v) : s_(std::to_string(v)) {}
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

// ── millis stub ────────────────────────────────────────────────────

static uint32_t mock_millis_value = 10000;
inline uint32_t millis() { return mock_millis_value; }

// ── ps_malloc stub ─────────────────────────────────────────────────

inline void* ps_malloc(size_t size) { return malloc(size); }

// ── esp_random stub ────────────────────────────────────────────────

inline uint32_t esp_random() { return 12345; }

// ── WiFi stub ──────────────────────────────────────────────────────

#define WL_CONNECTED 3

static int mock_wifi_status = 0;  // 0 = disconnected by default
struct MockWiFi {
    int status() { return mock_wifi_status; }
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
    bool available() { return false; }
    int read(uint8_t*, size_t) { return 0; }
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

static bool mock_upload_should_succeed = true;
static std::vector<std::string> mock_uploaded_files;

inline bool uploadFile(const char* filename) {
    mock_uploaded_files.push_back(std::string(filename));
    return mock_upload_should_succeed;
}

// ── Preferences stub ───────────────────────────────────────────────

struct Preferences {
    void begin(const char*, bool = false) {}
    void putUInt(const char*, uint32_t) {}
    uint32_t getUInt(const char*, uint32_t def = 0) { return def; }
    void putBool(const char*, bool) {}
    bool getBool(const char*, bool def = false) { return def; }
    void end() {}
};

// ── ArduinoOTA stub ────────────────────────────────────────────────

struct ArduinoOTAClass {
    void begin() {}
    void handle() {}
};
static ArduinoOTAClass ArduinoOTA;  // NOLINT — intentional global

// ── WiFiManager stub ───────────────────────────────────────────────

struct WiFiManager {
    void autoConnect(const char*) {}
    String ssid() { return "MockSSID"; }
    String psk() { return "mockpass"; }
};

// ── RemoteDebug stub ───────────────────────────────────────────────

struct RemoteDebug {
    void begin(const char*) {}
    void handle() {}
};

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
