#!/usr/bin/env python3
"""
ESP32-S3-WROOM-1U-N8R8 data-logger — FINAL SKiDL generator (frozen rev A)
Target : KiCad 10.0.7 libraries ; JLCPCB + LCSC single-source PCBA
Blocks : 8-bit DVP camera (+4-bit fallback), 2x T3902 PDM mics,
         BQ25895+CH224K charger, MAX17048 gauge, TPS63020 3V3 rail,
         3x camera LDO, microSD 4-bit, USB-C, remote NTC (J4),
         battery connector J5 + DMP3013SFV-7 reverse-polarity P-FET.
"""
from skidl import *
set_default_tool(KICAD10)          # explicit; generic KICAD mirrors KICAD10

# --- point SKiDL at your KiCad 10 libraries ---
KICAD_SYM = "/usr/share/kicad/symbols/"        # adjust to your install
KICAD_FP  = "/usr/share/kicad/footprints/"
lib_search_paths[KICAD10].append(KICAD_SYM)
lib_search_paths[KICAD].append(KICAD_SYM)
footprint_search_paths[KICAD10].append(KICAD_FP)

set_default_tool(KICAD)

# ===================== BUILD-TIME OPTIONS =====================
CAM_BITS   = 8      # 8 = full DVP ; 4 = fallback (frees GPIO12/16/17/18)
SHARED_INT = False  # True = FUEL_ALERT + CHG_INT share GPIO1 (frees GPIO2)

# ===================== AUDITED PIN MAP ========================
# GPIO33/34 not broken out; GPIO35/36/37 = octal PSRAM (unusable)
PIN = {
    'I2C_SDA':4, 'I2C_SCL':5,
    'CAM_XCLK':15, 'CAM_PCLK':13, 'CAM_VSYNC':6, 'CAM_HREF':7,
    'CAM_D0':11, 'CAM_D1':9, 'CAM_D2':8,  'CAM_D3':10,
    'CAM_D4':12, 'CAM_D5':18, 'CAM_D6':17, 'CAM_D7':16,
    'CAM_RESET':14,
    'SD_CLK':39, 'SD_CMD':38, 'SD_D0':40, 'SD_D1':41,
    'SD_D2':42,  'SD_D3':47,  'SD_CD':48,
    'PDM_CLK':43, 'PDM_DATA':44,
    'USB_DM':19, 'USB_DP':20,
    'FUEL_ALERT':1, 'CHG_INT':2, 'CHG_CE':3,
    'STATUS_LED':21, 'BOOT':0,
}

# ===================== CUSTOM SYMBOLS =========================
esp32_t = Part(tool=SKIDL, name='ESP32-S3-WROOM-1U-N8R8', dest=TEMPLATE, pins=[
    Pin(num='1',  name='GND', func=Pin.types.PWRIN),
    Pin(num='2',  name='3V3', func=Pin.types.PWRIN),
    Pin(num='3',  name='EN',  func=Pin.types.INPUT),
    Pin(num='4',  name='IO4'),  Pin(num='5',  name='IO5'),
    Pin(num='6',  name='IO6'),  Pin(num='7',  name='IO7'),
    Pin(num='8',  name='IO15'), Pin(num='9',  name='IO16'),
    Pin(num='10', name='IO17'), Pin(num='11', name='IO18'),
    Pin(num='12', name='IO8'),  Pin(num='13', name='IO19'),
    Pin(num='14', name='IO20'), Pin(num='15', name='IO3'),
    Pin(num='16', name='IO46'), Pin(num='17', name='IO9'),
    Pin(num='18', name='IO10'), Pin(num='19', name='IO11'),
    Pin(num='20', name='IO12'), Pin(num='21', name='IO13'),
    Pin(num='22', name='IO14'), Pin(num='23', name='IO21'),
    Pin(num='24', name='IO47'), Pin(num='25', name='IO48'),
    Pin(num='26', name='IO45'), Pin(num='27', name='IO0'),
    Pin(num='28', name='IO35'), Pin(num='29', name='IO36'),
    Pin(num='30', name='IO37'), Pin(num='31', name='IO38'),
    Pin(num='32', name='IO39'), Pin(num='33', name='IO40'),
    Pin(num='34', name='IO41'), Pin(num='35', name='IO42'),
    Pin(num='36', name='IO44'), Pin(num='37', name='IO43'),
    Pin(num='38', name='IO2'),  Pin(num='39', name='IO1'),
    Pin(num='40', name='GND',  func=Pin.types.PWRIN),
    Pin(num='41', name='EPAD', func=Pin.types.PWRIN),
])

cam_t = Part(tool=SKIDL, name='FPC24_0.5MM_DVP', dest=TEMPLATE, pins=[
    Pin(num='1',  name='AVDD28'), Pin(num='2',  name='AVDD28'),
    Pin(num='3',  name='DGND'),   Pin(num='4',  name='DOVDD18'),
    Pin(num='5',  name='SIOC'),   Pin(num='6',  name='SIOD'),
    Pin(num='7',  name='VSYNC'),  Pin(num='8',  name='HREF'),
    Pin(num='9',  name='PCLK'),   Pin(num='10', name='XCLK'),
    Pin(num='11', name='D0'),     Pin(num='12', name='D1'),
    Pin(num='13', name='D2'),     Pin(num='14', name='D3'),
    Pin(num='15', name='D4'),     Pin(num='16', name='D5'),
    Pin(num='17', name='D6'),     Pin(num='18', name='D7'),
    Pin(num='19', name='RESET'),  Pin(num='20', name='PWDN'),
    Pin(num='21', name='DVDD15'), Pin(num='22', name='DGND'),
    Pin(num='23', name='AGND'),   Pin(num='24', name='AGND'),
])

sdcard_t = Part(tool=SKIDL, name='MICROSD_PUSHPUSH', dest=TEMPLATE, pins=[
    Pin(num='1', name='DAT2'), Pin(num='2', name='DAT3'),
    Pin(num='3', name='CMD'),  Pin(num='4', name='VDD'),
    Pin(num='5', name='CLK'),  Pin(num='6', name='VSS'),
    Pin(num='7', name='DAT0'), Pin(num='8', name='DAT1'),
    Pin(num='9', name='CD'),   Pin(num='10', name='VSS'),
    Pin(num='11', name='VSS'),
])

usbc_t = Part(tool=SKIDL, name='USB_C_16P', dest=TEMPLATE, pins=[
    Pin(num='A1', name='GND'), Pin(num='A4', name='VBUS'),
    Pin(num='A5', name='CC1'), Pin(num='A6', name='DP1'),
    Pin(num='A7', name='DN1'), Pin(num='A8', name='SBU1'),
    Pin(num='B1', name='GND'), Pin(num='B4', name='VBUS'),
    Pin(num='B5', name='CC2'), Pin(num='B6', name='DP2'),
    Pin(num='B7', name='DN2'), Pin(num='B8', name='SBU2'),
    Pin(num='S1', name='SHIELD'),
])

mic_t = Part(tool=SKIDL, name='T3902_PDM_MIC', dest=TEMPLATE, pins=[
    Pin(num='1', name='VDD'), Pin(num='2', name='CLK'),
    Pin(num='3', name='DATA'), Pin(num='4', name='LR_SEL'),
    Pin(num='5', name='GND'),
])

gauge_t = Part(tool=SKIDL, name='MAX17048', dest=TEMPLATE, pins=[
    Pin(num='1', name='VDD'), Pin(num='2', name='CELL'),
    Pin(num='3', name='ALRT'), Pin(num='4', name='SDA'),
    Pin(num='5', name='SCL'), Pin(num='6', name='GND'),
    Pin(num='7', name='CTG'), Pin(num='8', name='QSTRT'),
])

pd_t = Part(tool=SKIDL, name='CH224K', dest=TEMPLATE, pins=[
    Pin(num='1', name='VDD'),   Pin(num='2', name='CFG1'),
    Pin(num='3', name='GND'),   Pin(num='4', name='VBUS'),
    Pin(num='5', name='PG'),    Pin(num='6', name='VBUS_IN'),
])

chg_t = Part(tool=SKIDL, name='BQ25895', dest=TEMPLATE, pins=[
    Pin(num='1',  name='VBUS'), Pin(num='2', name='D+'),
    Pin(num='3',  name='D-'),   Pin(num='4', name='STAT'),
    Pin(num='5',  name='SCL'),  Pin(num='6', name='SDA'),
    Pin(num='7',  name='INT'),  Pin(num='8', name='CE'),
    Pin(num='9',  name='BAT'),  Pin(num='10', name='SYS'),
    Pin(num='11', name='PGND'), Pin(num='12', name='SW'),
    Pin(num='13', name='BTST'), Pin(num='14', name='REGN'),
    Pin(num='15', name='TS'),   Pin(num='16', name='ILIM'),
    Pin(num='17', name='DSEL'), Pin(num='18', name='OTG'),
    Pin(num='19', name='PGND2'),Pin(num='20', name='PG'),
])

buck_t = Part(tool=SKIDL, name='TPS63020', dest=TEMPLATE, pins=[
    Pin(num='1', name='VIN'), Pin(num='2', name='VINA'),
    Pin(num='3', name='PGND'),Pin(num='4', name='PG'),
    Pin(num='5', name='FB'),  Pin(num='6', name='VOUT'),
    Pin(num='7', name='L1'),  Pin(num='8', name='L2'),
    Pin(num='9', name='EN'),  Pin(num='10', name='PS/SYNC'),
])

ldo_t = Part(tool=SKIDL, name='LDO_SOT23_5', dest=TEMPLATE, pins=[
    Pin(num='1', name='VIN'), Pin(num='2', name='GND'),
    Pin(num='3', name='EN'),  Pin(num='4', name='NC'),
    Pin(num='5', name='VOUT'),
])

conn2_t = Part(tool=SKIDL, name='CONN_2PIN', dest=TEMPLATE, pins=[
    Pin(num='1', name='P1'), Pin(num='2', name='P2'),
])

# PowerDI3333-8 (DFN) P-FET : 1,2,3=S ; 4=G ; 5-8+tab=D
pfet_t = Part(tool=SKIDL, name='DMP3013SFV-7', dest=TEMPLATE, pins=[
    Pin(num='1', name='S'), Pin(num='2', name='S'), Pin(num='3', name='S'),
    Pin(num='4', name='G'),
    Pin(num='5', name='D'), Pin(num='6', name='D'),
    Pin(num='7', name='D'), Pin(num='8', name='D'),
    Pin(num='9', name='D_TAB'),
])

# ===================== NETS ===================================
gnd   = Net('GND');   gnd.drive = POWER
vbus  = Net('VBUS');  vbus.drive = POWER
vsys  = Net('VSYS');  vsys.drive = POWER
v33   = Net('+3V3');  v33.drive = POWER
v28   = Net('+2V8');  v28.drive = POWER
v18   = Net('+1V8');  v18.drive = POWER
v15   = Net('+1V5');  v15.drive = POWER
vbat  = Net('VBAT');  vbat.drive = POWER      # protected rail (post-FET)
battp = Net('BATT+'); battp.drive = POWER     # raw battery + at J5
vbus_pd = Net('VBUS_PD')
vsw = Net('CHG_SW'); vregn = Net('CHG_REGN'); vbtst = Net('CHG_BTST')
vpmid = Net('CHG_PMID')
vfb = Net('BUCK_FB'); vsw_buck = Net('BUCK_SW')
i2c_sda = Net('I2C_SDA'); i2c_scl = Net('I2C_SCL')
cam_xclk = Net('CAM_XCLK'); cam_pclk = Net('CAM_PCLK')
cam_vsync = Net('CAM_VSYNC'); cam_href = Net('CAM_HREF')
cam_d = [Net(f'CAM_D{i}') for i in range(8)]
cam_rst = Net('CAM_RESET')
sd_clk = Net('SD_CLK'); sd_cmd = Net('SD_CMD')
sd_d = [Net(f'SD_D{i}') for i in range(4)]
sd_cd = Net('SD_CD')
pdm_clk = Net('PDM_CLK'); pdm_data = Net('PDM_DATA')
usb_dp = Net('USB_DP'); usb_dm = Net('USB_DM')
fuel_alert = Net('FUEL_ALERT'); chg_int = Net('CHG_INT')
chg_ce = Net('CHG_CE'); led = Net('STATUS_LED'); boot = Net('BOOT')
cc1 = Net('CC1'); cc2 = Net('CC2')
chg_ts = Net('CHG_TS')

def r(val): return Part('Device', 'R', value=val)
def c(val): return Part('Device', 'C', value=val)
def l(val): return Part('Device', 'L', value=val)

# ===================== 1. MCU + ESP32 externals ===============
u1 = esp32_t()
u1['3V3'] += v33; u1['GND'] += gnd; u1['EPAD'] += gnd
u1['IO4'] += i2c_sda; u1['IO5'] += i2c_scl
u1['IO15'] += cam_xclk; u1['IO13'] += cam_pclk
u1['IO6'] += cam_vsync; u1['IO7'] += cam_href
cam_pins = [11, 9, 8, 10, 12, 18, 17, 16]
for i in range(CAM_BITS):
    u1[f'IO{cam_pins[i]}'] += cam_d[i]
u1['IO14'] += cam_rst
u1['IO39'] += sd_clk; u1['IO38'] += sd_cmd
for i in range(4):
    u1[f'IO{[40,41,42,47][i]}'] += sd_d[i]
u1['IO48'] += sd_cd
u1['IO43'] += pdm_clk; u1['IO44'] += pdm_data
u1['IO19'] += usb_dm; u1['IO20'] += usb_dp
u1['IO1'] += fuel_alert
if SHARED_INT: u1['IO1'] += chg_int
else:          u1['IO2'] += chg_int
u1['IO3'] += chg_ce; u1['IO21'] += led; u1['IO0'] += boot

r_en = r('10k'); c_en = c('1uF')             # EN RC delay
r_en[1] += v33; r_en[2] += u1['EN']
c_en[1] += u1['EN']; c_en[2] += gnd
r_boot = r('10k'); r_boot[1] += v33; r_boot[2] += boot
r_dp = r('22'); r_dp[1] += u1['IO20']; r_dp[2] += usb_dp
r_dm = r('22'); r_dm[1] += u1['IO19']; r_dm[2] += usb_dm
for val in ['0.1u','10u','1u']:
    cc = c(val); cc[1] += v33; cc[2] += gnd

# ===================== 2. Camera FPC ==========================
j1 = cam_t()
j1['AVDD28'] += v28, v28; j1['DOVDD18'] += v18; j1['DVDD15'] += v15
j1['DGND'] += gnd, gnd; j1['AGND'] += gnd, gnd
j1['SIOC'] += i2c_scl; j1['SIOD'] += i2c_sda
j1['VSYNC'] += cam_vsync; j1['HREF'] += cam_href
j1['PCLK'] += cam_pclk; j1['XCLK'] += cam_xclk
for i in range(CAM_BITS): j1[f'D{i}'] += cam_d[i]
j1['RESET'] += cam_rst; j1['PWDN'] += gnd

# ===================== 3. PDM mics ============================
for lr_net in (gnd, v18):
    m = mic_t()
    m['VDD'] += v18; m['GND'] += gnd
    m['CLK'] += pdm_clk; m['DATA'] += pdm_data; m['LR_SEL'] += lr_net
    cd = c('0.1u'); cd[1] += v18; cd[2] += gnd

# ===================== 4. MAX17048 gauge ======================
u2 = gauge_t()
u2['VDD'] += v33; u2['GND'] += gnd; u2['CELL'] += vbat
u2['SDA'] += i2c_sda; u2['SCL'] += i2c_scl
u2['QSTRT'] += gnd; u2['CTG'] += gnd; u2['ALRT'] += fuel_alert
cg = c('0.1u'); cg[1] += v33; cg[2] += gnd
r_alrt = r('10k'); r_alrt[1] += v33; r_alrt[2] += fuel_alert

# ===================== 5. CH224K PD sink ======================
u3 = pd_t()
u3['GND'] += gnd; u3['VBUS_IN'] += vbus
r_pd_vdd = r('1k');  r_pd_vdd[1] += vbus; r_pd_vdd[2] += u3['VDD']
r_pd_vb  = r('10k'); r_pd_vb[1]  += vbus; r_pd_vb[2]  += u3['VBUS']
c_pd = c('1uF'); c_pd[1] += u3['VDD']; c_pd[2] += gnd
r_cfg = r('24k'); r_cfg[1] += u3['CFG1']; r_cfg[2] += gnd     # 24k -> 12V
u3['PG'] += Net('PD_PG')

# ===================== 6. BQ25895 charger =====================
u4 = chg_t()
u4['VBUS'] += vbus_pd; u4['BAT'] += vbat; u4['SYS'] += vsys
u4['PGND'] += gnd, gnd
u4['SCL'] += i2c_scl; u4['SDA'] += i2c_sda
u4['INT'] += chg_int; u4['CE'] += chg_ce
u4['D+'] += usb_dp; u4['D-'] += usb_dm; u4['OTG'] += gnd
u4['SW'] += vsw; u4['BTST'] += vbtst; u4['REGN'] += vregn
u4['TS'] += chg_ts; u4['ILIM'] += Net('CHG_ILIM')
l_chg = l('2.2u'); l_chg[1] += vsw; l_chg[2] += vsys
c_vbusin = c('8.2u'); c_vbusin[1] += vbus_pd; c_vbusin[2] += gnd
c_pmid = c('8.2u'); c_pmid[1] += vpmid; c_pmid[2] += gnd
for _ in range(2):
    cc = c('10u'); cc[1] += vsys; cc[2] += gnd
c_bat = c('10u'); c_bat[1] += vbat; c_bat[2] += gnd
c_regn = c('4.7u'); c_regn[1] += vregn; c_regn[2] += gnd
c_btst = c('47n'); c_btst[1] += vsw; c_btst[2] += vbtst
r_ilim = r('260'); r_ilim[1] += u4['ILIM']; r_ilim[2] += gnd
# TS network: fixed divider ON-BOARD, NTC REMOTE via J4
r_ts1 = r('5.23k'); r_ts1[1] += vregn; r_ts1[2] += chg_ts
r_ts2 = r('30.1k'); r_ts2[1] += chg_ts; r_ts2[2] += gnd
j4 = conn2_t(); j4['P1'] += chg_ts; j4['P2'] += gnd
r_stat = r('10k'); r_stat[1] += vsys; r_stat[2] += u4['STAT']

# ===================== 7. Battery J5 + reverse P-FET ==========
j5 = conn2_t(); j5['P1'] += battp; j5['P2'] += gnd
q_rev = pfet_t()
q_rev['D'] += battp; q_rev['D_TAB'] += battp   # drain -> battery +
q_rev['S'] += vbat                             # source -> protected rail
q_rev['G'] += Net('Q_REV_GATE')
r_g = r('100k'); r_g[1] += q_rev['G']; r_g[2] += gnd

# ===================== 8. TPS63020 buck-boost =================
u5 = buck_t()
u5['VIN'] += vsys; u5['VINA'] += vsys; u5['PGND'] += gnd
u5['EN'] += vsys; u5['PS/SYNC'] += gnd
u5['L1'] += vsw_buck; u5['L2'] += v33
u5['VOUT'] += v33; u5['FB'] += vfb
l_bk = l('1.5u'); l_bk[1] += vsw_buck; l_bk[2] += v33
for _ in range(2):
    cc = c('10u'); cc[1] += vsys; cc[2] += gnd
for _ in range(3):
    cc = c('22u'); cc[1] += v33; cc[2] += gnd
c_vina = c('0.1u'); c_vina[1] += vsys; c_vina[2] += gnd
r_fb1 = r('1M');   r_fb1[1] += v33; r_fb1[2] += vfb
r_fb2 = r('180k'); r_fb2[1] += vfb; r_fb2[2] += gnd
r_pg  = r('1M');   r_pg[1]  += v33; r_pg[2]  += u5['PG']

# ===================== 9. Camera LDOs =========================
for rail, partname in [(v28,'AP2112K-2.8'),(v18,'AP2112K-1.8'),(v15,'TLV70015')]:
    ld = ldo_t(); ld.fields['MPN'] = partname
    ld['VIN'] += v33; ld['EN'] += v33; ld['GND'] += gnd; ld['VOUT'] += rail
    ci = c('1u'); ci[1] += v33; ci[2] += gnd
    co = c('1u'); co[1] += rail; co[2] += gnd

# ===================== 10. microSD ============================
j2 = sdcard_t()
j2['VDD'] += v33; j2['VSS'] += gnd, gnd, gnd
j2['CLK'] += sd_clk; j2['CMD'] += sd_cmd
for i in range(4): j2[f'DAT{i}'] += sd_d[i]
j2['CD'] += sd_cd
r_cmd = r('10k'); r_cmd[1] += v33; r_cmd[2] += sd_cmd
for i in range(4):
    rr = r('10k'); rr[1] += v33; rr[2] += sd_d[i]
r_cd = r('10k'); r_cd[1] += v33; r_cd[2] += sd_cd
c_sd1 = c('0.1u'); c_sd1[1] += v33; c_sd1[2] += gnd
c_sd2 = c('10u');  c_sd2[1] += v33; c_sd2[2] += gnd

# ===================== 11. USB-C + buttons + LED ==============
j3 = usbc_t()
j3['VBUS'] += vbus, vbus; j3['GND'] += gnd, gnd; j3['SHIELD'] += gnd
j3['DP1'] += usb_dp; j3['DP2'] += usb_dp
j3['DN1'] += usb_dm; j3['DN2'] += usb_dm
r_cc1 = r('5.1k'); r_cc1[1] += j3['CC1']; r_cc1[2] += gnd
r_cc2 = r('5.1k'); r_cc2[1] += j3['CC2']; r_cc2[2] += gnd
boot_sw = Part('Switch','SW_Push')(); boot_sw[1] += boot; boot_sw[2] += gnd
rst_sw  = Part('Switch','SW_Push')(); rst_sw[1] += u1['EN']; rst_sw[2] += gnd
r_led = r('330'); d_led = Part('Device','LED')()
r_led[1] += led; r_led[2] += d_led['A']; d_led['K'] += gnd

# ===================== 12. I2C pull-ups =======================
for net in (i2c_sda, i2c_scl):
    rr = r('4.7k'); rr[1] += v33; rr[2] += net

# ===================== OUTPUT =================================
ERC()
generate_netlist(file_='esp32s3_datalogger.net')
#generate_bom(file_='esp32s3_datalogger_bom.csv')
