#!/usr/bin/env python3
"""
ESP32-S3-WROOM-1U-N8R8 data-logger — SKiDL generator (rev C: max-stock build)
KiCad 10.x ; JLCPCB + LCSC single-source PCBA.
rev C uses official KiCad symbols for EVERYTHING that has one, so pins AND
footprints come from the library. Custom symbols remain ONLY for the four
parts KiCad does not ship: TPS63020, MAX17048, CH224K, T3902.
Stock symbols: ESP32-S3-WROOM-1, Micro_SD_Card_Det2, USB_C_Receptacle_USB2.0_16P,
               BQ25895RTW, DMP3013SFV, AP2127K-{1.5,1.8,2.8}, Conn_01x02, Conn_01x24
"""
from skidl import *
import os

# ---- library search paths (in-script; no shell env needed) ----
KICAD_SYM = "/usr/share/kicad/symbols"
KICAD_FP  = "/usr/share/kicad/footprints"
PROJ_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")


set_default_tool(KICAD10)
for _t in (KICAD10, KICAD):
    lib_search_paths[_t].append(KICAD_SYM)
    lib_search_paths[_t].append(PROJ_LIB)          # <-- generated symbols
    footprint_search_paths[_t].append(KICAD_FP)
    footprint_search_paths[_t].append(PROJ_LIB)    # <-- generated .pretty dirs


CAM_BITS   = 8
SHARED_INT = False

# ---- helper: tie several pin NUMBERS of one part to a net ----
def tie(part, nums, net):
    for n in nums:
        part[n] += net

# ===================== STOCK SYMBOLS ==========================
esp32_t  = Part('RF_Module',          'ESP32-S3-WROOM-1',            dest=TEMPLATE)
sdcard_t = Part('Connector',          'Micro_SD_Card_Det2',          dest=TEMPLATE)
usbc_t   = Part('Connector',          'USB_C_Receptacle_USB2.0_16P', dest=TEMPLATE)
chg_t    = Part('Battery_Management', 'BQ25895RTW',                  dest=TEMPLATE)
pfet_t   = Part('Transistor_FET',     'DMP3013SFV',                  dest=TEMPLATE)
ldo15_t  = Part('Regulator_Linear',   'AP2127K-1.5',                 dest=TEMPLATE)
ldo18_t  = Part('Regulator_Linear',   'AP2127K-1.8',                 dest=TEMPLATE)
ldo28_t  = Part('Regulator_Linear',   'AP2127K-2.8',                 dest=TEMPLATE)
conn2_t  = Part('Connector_Generic',  'Conn_01x02',                  dest=TEMPLATE)
conn24_t = Part('Connector_Generic',  'Conn_01x24',                  dest=TEMPLATE)
gauge_t = Part('MAX17048', 'MAX17048G+T10',   dest=TEMPLATE)
buck_t  = Part('TPS63020', 'TPS63020DSJR',    dest=TEMPLATE)
pd_t    = Part('CH224K',   'CH224K',          dest=TEMPLATE)
mic_t   = Part('T3902',    'MMICT390200012',  dest=TEMPLATE)

for t in (gauge_t, buck_t, pd_t, mic_t):
    print('\n===', t.name, '===')
    for p in t.pins:
        print(f'  {p.num:>3}  {p.name!r}')   # !r shows the exact string, incl. '#'

# ESP32 is the -1 (onboard-antenna) symbol; we override the footprint to the
# -1U external-antenna land pattern. Pinout is identical.
esp32_t.footprint = 'RF_Module:ESP32-S3-WROOM-1U'
sdcard_t.footprint = 'Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5'   # VERIFY vs socket
usbc_t.footprint   = 'Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12' # VERIFY vs socket
conn24_t.footprint = 'Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal'  # J1
conn2_t.footprint  = 'Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical'                  # J5 battery
conn2_t.footprint  = 'Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical'                  # J4 NTC (pick yours)

# ===================== NETS ===================================
gnd=Net('GND'); vbus=Net('VBUS'); vsys=Net('VSYS')
v33=Net('+3V3'); v28=Net('+2V8'); v18=Net('+1V8'); v15=Net('+1V5')
vbat=Net('VBAT'); battp=Net('BATT+')
for _n in (gnd, vbus, vsys, v33, v28, v18, v15, vbat, battp): _n.drive = POWER
vbus_pd=Net('VBUS_PD'); vsw=Net('CHG_SW'); vregn=Net('CHG_REGN'); vbtst=Net('CHG_BTST')
vpmid=Net('CHG_PMID'); vfb=Net('BUCK_FB'); vsw_buck=Net('BUCK_SW')
i2c_sda=Net('I2C_SDA'); i2c_scl=Net('I2C_SCL')
cam_xclk=Net('CAM_XCLK'); cam_pclk=Net('CAM_PCLK'); cam_vsync=Net('CAM_VSYNC')
cam_href=Net('CAM_HREF'); cam_rst=Net('CAM_RESET')
cam_d=[Net(f'CAM_D{i}') for i in range(8)]
sd_clk=Net('SD_CLK'); sd_cmd=Net('SD_CMD'); sd_d=[Net(f'SD_D{i}') for i in range(4)]
sd_cd=Net('SD_CD'); pdm_clk=Net('PDM_CLK'); pdm_data=Net('PDM_DATA')
usb_dp=Net('USB_DP'); usb_dm=Net('USB_DM')
fuel_alert=Net('FUEL_ALERT'); chg_int=Net('CHG_INT'); chg_ce=Net('CHG_CE')
led=Net('STATUS_LED'); boot=Net('BOOT'); chg_ts=Net('CHG_TS')

def r(v, fp='Resistor_SMD:R_0805_2012Metric'):  return Part('Device','R',value=v,footprint=fp)
def c(v, fp='Capacitor_SMD:C_0805_2012Metric'): return Part('Device','C',value=v,footprint=fp)
def l(v, fp='Inductor_SMD:L_1210_3225Metric'):  return Part('Device','L',value=v,footprint=fp)

# ===================== 1. MCU (by PIN NUMBER) =================
u1 = esp32_t()
tie(u1, (1, 40, 41), gnd)      # GND + GND + EPAD
u1[2]  += v33                  # 3V3
u1[4]  += i2c_sda; u1[5]  += i2c_scl
u1[8]  += cam_xclk; u1[21] += cam_pclk; u1[6] += cam_vsync; u1[7] += cam_href
for i, p in enumerate((19, 17, 12, 18, 20, 11, 10, 9)):   # CAM_D0..D7
    u1[p] += cam_d[i]
u1[22] += cam_rst
u1[32] += sd_clk; u1[31] += sd_cmd
for i, p in enumerate((33, 34, 35, 24)): u1[p] += sd_d[i]   # SD_D0..D3
u1[25] += sd_cd
u1[37] += pdm_clk              # IO43 = TXD0
u1[36] += pdm_data             # IO44 = RXD0
u1[13] += usb_dm; u1[14] += usb_dp
u1[39] += fuel_alert           # IO1
u1[38] += chg_int              # IO2 (or u1[39] if SHARED_INT)
u1[15] += chg_ce; u1[23] += led; u1[27] += boot

r_en=r('10k'); c_en=c('1uF')
r_en[1]+=v33; r_en[2]+=u1[3]; c_en[1]+=u1[3]; c_en[2]+=gnd   # EN RC
r_boot=r('10k'); r_boot[1]+=v33; r_boot[2]+=boot
r_dp=r('22'); r_dp[1]+=u1[14]; r_dp[2]+=usb_dp
r_dm=r('22'); r_dm[1]+=u1[13]; r_dm[2]+=usb_dm
for v in ('0.1u','10u','1u'):
    x=c(v); x[1]+=v33; x[2]+=gnd

# ===================== 2. Camera FPC (Conn_01x24) =============
CAM = {1:v28,2:v28,3:gnd,4:v18,5:i2c_scl,6:i2c_sda,7:cam_vsync,8:cam_href,
       9:cam_pclk,10:cam_xclk,19:cam_rst,20:gnd,21:v15,22:gnd,23:gnd,24:gnd}
j1 = conn24_t()
for p,net in CAM.items(): j1[p] += net
for i in range(8): j1[11+i] += cam_d[i]

# ===================== 3. PDM mics ============================
for lr in (gnd, v18):
    m = mic_t()
    m['VDD']+=v18; m['GND']+=gnd; m['CLK']+=pdm_clk; m['DATA']+=pdm_data; m['SELECT']+=lr
    x=c('0.1u'); x[1]+=v18; x[2]+=gnd

# ===================== 4. MAX17048 ============================
u2 = gauge_t()
u2['VDD']+=v33; u2['GND']+=gnd; u2['CELL']+=vbat
u2['SDA']+=i2c_sda; u2['SCL']+=i2c_scl
u2['QSTRT']+=gnd; u2['CTG']+=gnd; u2['~{ALRT}']+=fuel_alert
x=c('0.1u'); x[1]+=v33; x[2]+=gnd
ra=r('10k'); ra[1]+=v33; ra[2]+=fuel_alert

# ===================== 5. CH224K ==============================
u3 = pd_t()
u3['GND']+=gnd; u3['VBUS']+=vbus
rp=r('1k');  rp[1]+=vbus; rp[2]+=u3['VDD']
rv=r('10k'); rv[1]+=vbus; rv[2]+=u3['VBUS']
x=c('1uF'); x[1]+=u3['VDD']; x[2]+=gnd
rc=r('24k'); rc[1]+=u3['CFG1']; rc[2]+=gnd
u3['PG'] += Net('PD_PG')

# ===================== 6. BQ25895RTW (by NUMBER) ==============
u4 = chg_t()
u4[1]+=vbus_pd; tie(u4,(13,14),vbat); tie(u4,(15,16),vsys); tie(u4,(17,18,25),gnd)
u4[5]+=i2c_scl; u4[6]+=i2c_sda
u4[7]+=chg_int; u4[9]+=chg_ce; u4[8]+=gnd          # ~INT, ~CE, OTG
u4[2]+=usb_dp; u4[3]+=usb_dm
u4[19]+=vsw; u4[20]+=vsw; u4[21]+=vbtst; u4[22]+=vregn; u4[23]+=vpmid
u4[11]+=chg_ts; u4[10]+=Net('CHG_ILIM'); u4[4]+=u4[4]   # STAT left for r_stat below
u4[24]+=Net('CHG_DSEL')                                  # DSEL (float/strap per design)
l_chg=l('2.2u'); l_chg[1]+=vsw; l_chg[2]+=vsys
for net,val in ((vbus_pd,'8.2u'),(vpmid,'8.2u'),(vbat,'10u'),(vregn,'4.7u')):
    x=c(val); x[1]+=net; x[2]+=gnd
for _ in range(2):
    x=c('10u'); x[1]+=vsys; x[2]+=gnd
x=c('47n'); x[1]+=vsw; x[2]+=vbtst
ri=r('260'); ri[1]+=u4[10]; ri[2]+=gnd
r_ts1=r('5.23k'); r_ts1[1]+=vregn; r_ts1[2]+=chg_ts
r_ts2=r('30.1k'); r_ts2[1]+=chg_ts; r_ts2[2]+=gnd
j4=conn2_t(); j4[1]+=chg_ts; j4[2]+=gnd
r_stat=r('10k'); r_stat[1]+=vsys; r_stat[2]+=u4[4]

# ===================== 7. Battery + reverse P-FET =============
j5=conn2_t(); j5[1]+=battp; j5[2]+=gnd
q=pfet_t()
tie(q,(1,2,3),vbat)      # S (x3) -> protected rail
q[4]+=Net('Q_REV_GATE')  # G
q[5]+=battp              # D -> battery + (D pins stacked in symbol)
rg=r('100k'); rg[1]+=q[4]; rg[2]+=gnd

# ===================== 8. TPS63020 buck-boost =================
u5=buck_t()
u5['VIN']+=vsys; u5['VINA']+=vsys; u5['PGND']+=gnd
u5['EN']+=vsys; u5['PS/SYNC']+=gnd
u5['L1']+=vsw_buck; u5['L2']+=v33; u5['VOUT']+=v33; u5['FB']+=vfb
lb=l('1.5u'); lb[1]+=vsw_buck; lb[2]+=v33
for _ in range(2):
    x=c('10u'); x[1]+=vsys; x[2]+=gnd
for _ in range(3):
    x=c('22u'); x[1]+=v33; x[2]+=gnd
x=c('0.1u'); x[1]+=vsys; x[2]+=gnd
rf1=r('1M'); rf1[1]+=v33; rf1[2]+=vfb
rf2=r('180k'); rf2[1]+=vfb; rf2[2]+=gnd
rpg=r('1M'); rpg[1]+=v33; rpg[2]+=u5['PG']

# ===================== 9. Camera LDOs (stock AP2127K) =========
for tpl, rail in ((ldo28_t,v28),(ldo18_t,v18),(ldo15_t,v15)):
    ld=tpl(); ld['VIN']+=v33; ld['EN']+=v33; ld['GND']+=gnd; ld['VOUT']+=rail
    ci=c('1u'); ci[1]+=v33; ci[2]+=gnd
    co=c('1u'); co[1]+=rail; co[2]+=gnd

# ===================== 10. microSD (by NUMBER) ================
j2=sdcard_t()
j2[4]+=v33; j2[6]+=gnd                      # VDD, VSS
j2[5]+=sd_clk; j2[3]+=sd_cmd
for i,p in enumerate((7,8,1,2)): j2[p]+=sd_d[i]   # DAT0,DAT1,DAT2,DAT3
j2[10]+=gnd; j2[9]+=sd_cd                   # DET_A->GND, DET_B->SD_CD
rcmd=r('10k'); rcmd[1]+=v33; rcmd[2]+=sd_cmd
for i in range(4):
    rr=r('10k'); rr[1]+=v33; rr[2]+=sd_d[i]
rcd=r('10k'); rcd[1]+=v33; rcd[2]+=sd_cd
x=c('0.1u'); x[1]+=v33; x[2]+=gnd
x=c('10u');  x[1]+=v33; x[2]+=gnd

# ===================== 11. USB-C + buttons + LED ==============
j3=usbc_t()
for p in ('A4','B4','A9','B9'): j3[p]+=vbus
for p in ('A1','B1','A12','B12','SH'): j3[p]+=gnd
j3['A5']+=Net('CC1'); j3['B5']+=Net('CC2')
j3['A6']+=usb_dp; j3['B6']+=usb_dp; j3['A7']+=usb_dm; j3['B7']+=usb_dm
rcc1=r('5.1k'); rcc1[1]+=j3['A5']; rcc1[2]+=gnd
rcc2=r('5.1k'); rcc2[1]+=j3['B5']; rcc2[2]+=gnd
bsw=Part('Switch','SW_Push',footprint='Button_Switch_SMD:SW_SPST_TL3342')()
bsw[1]+=boot; bsw[2]+=gnd
rsw=Part('Switch','SW_Push',footprint='Button_Switch_SMD:SW_SPST_TL3342')()
rsw[1]+=u1[3]; rsw[2]+=gnd
rl=r('330'); d=Part('Device','LED',footprint='LED_SMD:LED_0805_2012Metric')()
rl[1]+=led; rl[2]+=d['A']; d['K']+=gnd

# ===================== 12. I2C pull-ups =======================
for net in (i2c_sda, i2c_scl):
    rr=r('4.7k'); rr[1]+=v33; rr[2]+=net

# ===================== OUTPUT =================================
# ERC()                                   # uncomment to run ERC
generate_netlist(file_='esp32s3_datalogger.net')
generate_xml(file_='esp32s3_datalogger.xml')   # BOM input for KiBoM etc.
