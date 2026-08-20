#pragma once
// Stubs for esp-sr symbols not in precompiled libraries.
// These are in AEC/wakenet code paths that never execute
// (aec_init=false, wakenet_init=false).
// Provided as weak symbols so they don't conflict if real
// implementations are linked.

#ifdef __cplusplus
extern "C" {
#endif

// FFT stubs (from esp-dl component, not in esp-sr libs)
void* __attribute__((weak)) dl_rfft_f32_init(int len, void *cfg) { (void)len; (void)cfg; return (void*)0; }
void  __attribute__((weak)) dl_rfft_f32_run(void *cfg, float *in, float *out) { (void)cfg; (void)in; (void)out; }
void  __attribute__((weak)) dl_rfft_f32_deinit(void *cfg) { (void)cfg; }
void* __attribute__((weak)) dl_rfft_s16_init(int len, void *cfg) { (void)len; (void)cfg; return (void*)0; }
void  __attribute__((weak)) dl_rfft_s16_hp_run(void *cfg, int16_t *in, int16_t *out) { (void)cfg; (void)in; (void)out; }
void  __attribute__((weak)) dl_rfft_s16_deinit(void *cfg) { (void)cfg; }
void  __attribute__((weak)) dl_irfft_f32_run(void *cfg, float *in, float *out) { (void)cfg; (void)in; (void)out; }
void  __attribute__((weak)) dl_irfft_s16_hp_run(void *cfg, int16_t *in, int16_t *out) { (void)cfg; (void)in; (void)out; }

// WakeNet handle stub — matches esp_wn_models.h declaration
// esp_wn_iface_t is already defined via esp_wn_iface.h (included by esp_afe_config.h)
const esp_wn_iface_t* __attribute__((weak)) esp_wn_handle_from_name(const char *name) { (void)name; return (const esp_wn_iface_t*)0; }

#ifdef __cplusplus
}

// C++ dotprod stub — weak so it doesn't conflict
namespace dl { namespace base {
void __attribute__((weak)) dotprod(float *a, float *b, float *out, int len, int shift) {
    (void)a; (void)b; (void)out; (void)len; (void)shift;
}
}}
#endif
