"""
Run this ON YOUR OWN MACHINE (not through Claude) to pull/refresh price
history for the pipe_dream universe, sidestepping the cloud sandbox's
network restrictions (and Twelve Data's 8-credit/minute, 800/day limits)
entirely -- yfinance makes its HTTP calls from your own network connection
when you run this yourself, so none of that applies.

Usage:
    pip install yfinance pandas
    python3 local_data_pull.py                     # pulls the full expanded universe + SPY (1621 tickers)
    python3 local_data_pull.py AAPL MSFT NVDA       # pulls just these tickers
    python3 local_data_pull.py --refresh-recent     # top up the last RECENT_DAYS days for every
                                                     # ticker that already has a CSV, instead of
                                                     # skipping it (see SKIP_EXISTING/REFRESH_ONLY_RECENT
                                                     # below -- this is the flag the dashboard's
                                                     # "refresh" buttons use for a daily top-up)
    python3 local_data_pull.py --refresh-recent AAPL MSFT   # can combine with an explicit ticker list

Output: writes one CSV per ticker to ./td_data_local/{TICKER}.csv with
columns [date, open, high, low, close, volume] -- same schema as the
project's existing data (dotted tickers like BRK.B keep the dot in the
filename; only the actual yfinance download call uses the hyphen form
BRK-B that Yahoo expects).

This file (and the td_data_local/ folder it writes into) should be
.gitignored -- it's raw market data, not source. Full ~19-year history for
all 1621 tickers is roughly 450-750 MB -- still comfortably manageable, but
noticeably bigger than the original 505-ticker S&P 500 pull. Because
SKIP_EXISTING (below) is on by default, re-running this script against a
folder that already has the original 505 S&P 500 CSVs in it will only
download the ~1,150 NEW tickers -- the overlap is skipped automatically.

Re-running this script is cheap and safe: it just overwrites each ticker's
CSV with fresh data, and SKIP_EXISTING (below) makes an interrupted run
resumable -- just run it again and it'll pick up where it left off. For a
daily refresh you don't need the full ~19-year history every time -- see
REFRESH_ONLY_RECENT below.

Send the resulting td_data_local/ folder (or just zip it) back so it can be
dropped in alongside the existing /tmp/td_data_yf files and the feature/backtest/
signal pipeline can be pointed at it.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("Missing dependency. Run: pip install yfinance pandas")
    sys.exit(1)

import pandas as pd

OUT_DIR = Path(__file__).parent / "td_data_local"
START_DATE = "2006-01-01"   # matches the cloud pipeline's history depth

# Expanded universe as of 2026-08-27 (1620 tickers) + SPY as a benchmark
# proxy for the index itself. Built from a raw market-cap/country/price
# screen (stockanalysis.com), NOT the S&P 500/400 membership lists:
#   - Market cap > $2B, Country = United States, Price > $10/share
#   - No 3-year-listed requirement (drop the old S&P eligibility screen)
#   - REITs included
#   - Dual-class shares deduped: keep only ONE ticker per company, preferring
#     the cheaper class UNLESS that class is effectively untraded, in which
#     case the liquid class is kept instead (e.g. AGM kept over AGM.A, whose
#     volume was 30 shares/day; LEN kept over LEN.B; MKC kept over MKC.V;
#     FWONK kept over FWONA)
#   - SPCX (SpaceX, which genuinely IPO'd -- the ~$1.9T market cap is real,
#     not a data artifact) excluded per Gabe's personal preference, not a
#     data-quality issue.
#   - Non-common-stock/duplicate-listing artifacts excluded (e.g. SOMN --
#     a near-zero-volume duplicate listing of Southern Co, keeping SO)
#   - Known stale/renamed tickers corrected for yfinance: MRSH -> MMC
#     (Marsh & McLennan), FISV -> FI (Fiserv)
#   - No separate liquidity filter needed: at this market-cap floor, all but
#     a literal handful of names already trade several million $/day
DEFAULT_UNIVERSE = [
    "A", "AA", "AADX", "AAL", "AAMI", "AAOI", "AAON", "AAP", "AAPL", "AB",
    "ABBV", "ABCB", "ABG", "ABM", "ABNB", "ABT", "ACA", "ACAD", "ACHC", "ACI",
    "ACIW", "ACLS", "ACM", "ACMR", "ACT", "AD", "ADBE", "ADC", "ADEA", "ADI",
    "ADM", "ADP", "ADPT", "ADSK", "ADUS", "AEE", "AEHR", "AEIS", "AEO", "AEP",
    "AES", "AFG", "AFL", "AFRM", "AGCO", "AGIO", "AGM", "AGNC", "AGX", "AGYS",
    "AHR", "AIG", "AIR", "AIT", "AIZ", "AJG", "AKAM", "AKR", "ALAB", "ALB",
    "ALG", "ALGM", "ALGN", "ALGT", "ALH", "ALHC", "ALK", "ALKT", "ALL", "ALLY",
    "ALM", "ALMR", "ALMS", "ALNY", "ALRM", "ALSN", "AM", "AMAT", "AMBA", "AMD",
    "AME", "AMG", "AMGN", "AMH", "AMKR", "AMLX", "AMP", "AMR", "AMRX", "AMT",
    "AMTM", "AMZN", "AN", "ANDE", "ANDG", "ANET", "ANF", "AOS", "APA", "APAM",
    "APD", "APG", "APGE", "APH", "APLD", "APLE", "APO", "APP", "APPF", "APPN",
    "AR", "ARCB", "ARCC", "ARE", "ARES", "ARLP", "ARMK", "AROC", "ARQT", "ARR",
    "ARW", "ARWR", "ARXS", "ASB", "ASH", "ASO", "ASTS", "ATI", "ATKR", "ATMU",
    "ATO", "ATR", "ATRC", "ATRO", "AU", "AUB", "AUGO", "AVA", "AVAH", "AVAV",
    "AVEX", "AVGO", "AVNT", "AVPT", "AVT", "AVTR", "AVY", "AWI", "AWK", "AWR",
    "AX", "AXGN", "AXON", "AXP", "AXSM", "AXTA", "AXTI", "AYI", "AZO", "AZZ",
    "BA", "BAC", "BAH", "BALL", "BAM", "BANC", "BANF", "BANR", "BATRA", "BATRK",
    "BAX", "BBIO", "BBT", "BBWI", "BBY", "BC", "BCC", "BCO", "BCPC", "BDC",
    "BDX", "BE", "BEAM", "BELFA", "BEN", "BEPC", "BETA", "BF.B", "BFAM", "BFH",
    "BG", "BGC", "BHE", "BHF", "BHVN", "BIIB", "BILL", "BIO", "BIPC", "BJ",
    "BKD", "BKE", "BKH", "BKNG", "BKR", "BKU", "BKV", "BLDR", "BLK", "BLKB",
    "BLLN", "BLTE", "BMI", "BMNR", "BMRN", "BMY", "BNL", "BNY", "BOBS", "BOH",
    "BOKF", "BOOT", "BOX", "BPOP", "BR", "BRC", "BRK.B", "BRKR", "BRO", "BROS",
    "BRX", "BRZE", "BSM", "BSX", "BSY", "BTSG", "BTU", "BURL", "BUSE", "BWA",
    "BWIN", "BWXT", "BX", "BXDC", "BXMT", "BXP", "BXSL", "BYD", "C", "CACC",
    "CACI", "CAG", "CAH", "CAI", "CAKE", "CALM", "CALX", "CALY", "CAR", "CARG",
    "CARR", "CART", "CASY", "CAT", "CATY", "CAVA", "CBC", "CBOE", "CBRE", "CBRS",
    "CBSH", "CBT", "CBU", "CBZ", "CC", "CCI", "CCK", "CCL", "CDE", "CDNA",
    "CDNS", "CDP", "CDW", "CE", "CECO", "CEG", "CELC", "CELH", "CENT", "CENX",
    "CF", "CFG", "CFR", "CG", "CGNX", "CGON", "CHCO", "CHD", "CHDN", "CHE",
    "CHEF", "CHH", "CHRD", "CHRN", "CHRW", "CHTR", "CHWY", "CHYM", "CI", "CIEN",
    "CIFR", "CINF", "CL", "CLBK", "CLDX", "CLF", "CLH", "CLMT", "CLSK", "CLX",
    "CMC", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNA", "CNC", "CNK", "CNM",
    "CNO", "CNP", "CNR", "CNS", "CNX", "CNXN", "COAG", "COCO", "COF", "COGT",
    "COHR", "COHU", "COIN", "COKE", "COLB", "COLD", "COLM", "COMP", "CON", "COO",
    "COP", "COR", "CORT", "CORZ", "COST", "CPAY", "CPB", "CPK", "CPNG", "CPRT",
    "CPT", "CQP", "CR", "CRBG", "CRC", "CRCL", "CRGY", "CRK", "CRL", "CRM",
    "CRNX", "CROX", "CRS", "CRUS", "CRVL", "CRWD", "CRWV", "CSCO", "CSGP", "CSL",
    "CSQR", "CSW", "CSX", "CTAS", "CTRE", "CTRI", "CTSH", "CTVA", "CUBE", "CUBI",
    "CURB", "CUZ", "CVBF", "CVCO", "CVI", "CVLT", "CVNA", "CVS", "CVSA", "CVX",
    "CW", "CWEN", "CWK", "CWST", "CWT", "CXT", "CXW", "CYTK", "CZR", "D",
    "DAL", "DAN", "DAR", "DASH", "DAVE", "DBD", "DBRG", "DBX", "DCI", "DCO",
    "DD", "DDOG", "DDS", "DE", "DECK", "DEI", "DELL", "DFTX", "DG", "DGII",
    "DGX", "DHI", "DHR", "DINO", "DIOD", "DIS", "DK", "DKL", "DKNG", "DKS",
    "DLB", "DLR", "DLTR", "DNLI", "DNOW", "DNTH", "DOC", "DOCN", "DOCS", "DOCU",
    "DORM", "DOV", "DOW", "DOX", "DPZ", "DRH", "DRI", "DRS", "DRVN", "DT",
    "DTE", "DTM", "DUK", "DUOL", "DV", "DVA", "DVN", "DX", "DXCM", "DXPE",
    "DY", "DYN", "EAT", "EBAY", "EBC", "ECG", "ECHO", "ECL", "ECPG", "ED",
    "EE", "EEFT", "EFSC", "EFX", "EGP", "EHC", "EIX", "EL", "ELAN", "ELF",
    "ELS", "ELV", "ELVN", "EME", "EMN", "EMR", "ENPH", "ENS", "ENSG", "ENTG",
    "ENVA", "EOG", "EPAM", "EPD", "EPR", "EPRT", "EQH", "EQIX", "EQPT", "EQT",
    "ERAS", "ERIE", "EROC", "EROK", "ES", "ESAB", "ESE", "ESI", "ESS", "ESTA",
    "ET", "ETR", "ETSY", "EVR", "EVRG", "EW", "EWBC", "EWTX", "EXC", "EXE",
    "EXEL", "EXLS", "EXP", "EXPD", "EXPE", "EXPO", "EXR", "EXTR", "EZPW", "F",
    "FA", "FAF", "FANG", "FAST", "FBIN", "FBK", "FBNC", "FBP", "FCF", "FCFS",
    "FCN", "FCNCA", "FCPT", "FCX", "FDS", "FDX", "FDXF", "FE", "FELE", "FERG",
    "FFBC", "FFIN", "FFIV", "FG", "FHB", "FHI", "FHN", "FI", "FIBK", "FICO",
    "FIG", "FIGR", "FIGS", "FIS", "FITB", "FIVE", "FIVN", "FIX", "FIZZ", "FLEX",
    "FLG", "FLNC", "FLR", "FLS", "FLUT", "FLY", "FLYW", "FNB", "FND", "FNF",
    "FORM", "FOUR", "FOX", "FPS", "FR", "FRHC", "FRME", "FROG", "FRPT", "FRSH",
    "FRT", "FRVO", "FSK", "FSLR", "FSLY", "FSS", "FTAI", "FTDR", "FTNT", "FTV",
    "FUL", "FULT", "FWONK", "GAP", "GATX", "GBCI", "GBDC", "GCMG", "GD", "GDDY",
    "GE", "GEF", "GEHC", "GEL", "GEN", "GENB", "GEO", "GEV", "GFF", "GFL",
    "GFS", "GGG", "GH", "GHC", "GILD", "GIS", "GKOS", "GL", "GLPI", "GLW",
    "GLXY", "GM", "GME", "GMED", "GNRC", "GNTX", "GOLF", "GOOG", "GPC", "GPCR",
    "GPGI", "GPI", "GPK", "GPN", "GPOR", "GRAL", "GRBK", "GRC", "GRDN", "GRND",
    "GS", "GSAT", "GSHD", "GTES", "GTLB", "GTX", "GTY", "GVA", "GWRE", "GWW",
    "GXO", "H", "HAE", "HAL", "HALO", "HAPN", "HAS", "HASI", "HAWK", "HAYW",
    "HBAN", "HCA", "HCC", "HCI", "HD", "HEI.A", "HESM", "HGTY", "HGV", "HHH",
    "HIG", "HII", "HIMS", "HIW", "HL", "HLI", "HLIO", "HLNE", "HLT", "HMN",
    "HNGE", "HNI", "HOG", "HOMB", "HON", "HONA", "HOOD", "HP", "HPE", "HPQ",
    "HQY", "HR", "HRB", "HRI", "HRL", "HRMY", "HSIC", "HST", "HSY", "HTFL",
    "HTGC", "HTH", "HTO", "HUBB", "HUBG", "HUBS", "HUM", "HURN", "HUT", "HWC",
    "HWKN", "HWM", "HXL", "HYMC", "IBKR", "IBM", "IBOC", "IBP", "ICE", "ICHR",
    "ICUI", "IDA", "IDCC", "IDXX", "IDYA", "IESC", "IEX", "IFF", "ILMN", "IMNM",
    "IMVT", "INCY", "INDB", "INDV", "INFQ", "INGM", "INGR", "INSM", "INSW", "INTA",
    "INTC", "INTU", "INVH", "IOND", "IONQ", "IONS", "IOSP", "IOT", "IP", "IPAR",
    "IPGP", "IQV", "IR", "IRDM", "IRM", "IRON", "IRT", "IRTC", "ISRG", "IT",
    "ITGR", "ITRI", "ITT", "ITW", "IVT", "IVZ", "J", "JAN", "JBHT", "JBL",
    "JBTM", "JEF", "JKHY", "JLL", "JMKE", "JNJ", "JOE", "JPM", "JXN", "KAI",
    "KALU", "KBH", "KBR", "KD", "KDP", "KEX", "KEY", "KEYS", "KFY", "KGS",
    "KHC", "KIM", "KKR", "KLAC", "KLRA", "KMB", "KMI", "KMT", "KMX", "KN",
    "KNF", "KNSL", "KNTK", "KNX", "KO", "KOD", "KR", "KRC", "KRG", "KRMN",
    "KRYS", "KSS", "KTB", "KTOS", "KVUE", "KVYO", "KWR", "KYMR", "L", "LAD",
    "LAMR", "LASR", "LAUR", "LAZ", "LB", "LBRT", "LCII", "LCLN", "LDOS", "LEA",
    "LECO", "LEGN", "LEN", "LEU", "LEVI", "LFST", "LFTO", "LFUS", "LGN", "LGND",
    "LH", "LHX", "LIF", "LIFE", "LII", "LIME", "LIND", "LINE", "LION", "LITE",
    "LKQ", "LLY", "LLYVA", "LMND", "LMT", "LNC", "LNG", "LNT", "LNTH", "LOAR",
    "LOPE", "LOW", "LPG", "LPLA", "LPX", "LQDA", "LRCX", "LRN", "LSCC", "LSTR",
    "LTC", "LTH", "LUNR", "LUV", "LVS", "LW", "LXP", "LYFT", "LYV", "M",
    "MA", "MAA", "MAC", "MAIN", "MAIR", "MAN", "MANE", "MANH", "MAR", "MARA",
    "MAS", "MAT", "MATX", "MBGL", "MBIN", "MBX", "MC", "MCD", "MCHB", "MCHP",
    "MCK", "MCO", "MCRI", "MCY", "MD", "MDB", "MDGL", "MDLN", "MDLZ", "MDU",
    "MEDP", "MET", "META", "MFP", "MGEE", "MGM", "MGNI", "MGRC", "MGY", "MH",
    "MHK", "MHO", "MIAX", "MIDD", "MIR", "MIRM", "MKC", "MKL", "MKSI", "MKTX",
    "MLI", "MLM", "MLYS", "MMC", "MMED", "MMM", "MMS", "MMSI", "MNR", "MNST",
    "MO", "MOD", "MOG.A", "MOH", "MORN", "MOS", "MP", "MPC", "MPLX", "MPWR",
    "MRCY", "MRK", "MRNA", "MRP", "MRVL", "MS", "MSA", "MSCI", "MSFT", "MSGE",
    "MSGS", "MSI", "MSM", "MSTR", "MTB", "MTCH", "MTDR", "MTG", "MTH", "MTN",
    "MTRN", "MTSI", "MTX", "MTZ", "MU", "MUR", "MUSA", "MWA", "MWH", "MXL",
    "MYRG", "MZTI", "NATL", "NAVN", "NBIX", "NBTB", "NCLH", "NCNO", "NDAQ", "NDSN",
    "NE", "NEE", "NEM", "NEO", "NEOG", "NESR", "NET", "NEU", "NFG", "NFLX",
    "NGL", "NGVT", "NHC", "NHI", "NI", "NIC", "NIQ", "NJR", "NKE", "NKTR",
    "NLY", "NMIH", "NMRK", "NN", "NNI", "NNN", "NOC", "NOG", "NOV", "NOVT",
    "NOW", "NP", "NPO", "NRG", "NRIX", "NSC", "NSIT", "NTAP", "NTCT", "NTNX",
    "NTRA", "NTRS", "NTSK", "NTST", "NUE", "NVDA", "NVR", "NVST", "NVTS", "NWBI",
    "NWE", "NWN", "NWSA", "NXST", "NXT", "NYT", "O", "OBDC", "OC", "OCTV",
    "OCUL", "ODFL", "OFG", "OGE", "OGN", "OGS", "OHI", "OII", "OKE", "OKLO",
    "OKTA", "OLED", "OLLI", "OMC", "OMF", "ON", "ONB", "ONTO", "OPCH", "OPLN",
    "ORA", "ORCL", "ORI", "ORKA", "ORLY", "OSCR", "OSIS", "OSK", "OTF", "OTIS",
    "OTTR", "OUST", "OUT", "OVV", "OWL", "OXY", "OZK", "P", "PAA", "PACS",
    "PAG", "PAGP", "PANW", "PARR", "PATH", "PATK", "PAY", "PAYC", "PAYX", "PB",
    "PBF", "PBH", "PBI", "PBLS", "PCAR", "PCG", "PCOR", "PCTY", "PCVX", "PEB",
    "PECO", "PEG", "PEGA", "PEN", "PENG", "PENN", "PEP", "PFE", "PFG", "PFGC",
    "PFS", "PFSI", "PG", "PGNY", "PGR", "PH", "PHIN", "PHM", "PI", "PII",
    "PINS", "PIPR", "PJT", "PK", "PKG", "PL", "PLD", "PLMR", "PLNT", "PLPC",
    "PLSE", "PLTR", "PLUS", "PLXS", "PM", "PNC", "PNFP", "PNW", "PODD", "POOL",
    "POR", "POST", "POWI", "POWL", "PPC", "PPG", "PPL", "PPLI", "PPTA", "PR",
    "PRAX", "PRDO", "PRI", "PRIM", "PRK", "PRM", "PRMB", "PRU", "PRVA", "PS",
    "PSA", "PSKY", "PSMT", "PSN", "PSUS", "PSX", "PTC", "PTCT", "PTEN", "PTGX",
    "PTRN", "PVH", "PVLA", "PWR", "PYPL", "Q", "QBTS", "QCOM", "QLYS", "QNT",
    "QRVO", "QSR", "QTWO", "QXO", "R", "RAL", "RAMP", "RAPP", "RARE", "RBA",
    "RBC", "RBLX", "RBRK", "RCL", "RCUS", "RDDT", "RDN", "RDNT", "RDW", "REG",
    "REGN", "RELY", "REXR", "REYN", "REZI", "RF", "RGA", "RGEN", "RGLD", "RGTI",
    "RH", "RHI", "RHP", "RIOT", "RITM", "RIVN", "RJF", "RKLB", "RKT", "RL",
    "RLAY", "RLI", "RMBS", "RMD", "RNG", "RNST", "ROAD", "ROG", "ROK", "ROKU",
    "ROL", "ROP", "ROST", "RPM", "RPRX", "RRC", "RRR", "RRX", "RS", "RSG",
    "RSI", "RTX", "RUSHB", "RVMD", "RVTY", "RXO", "RYAN", "RYN", "RYTM", "S",
    "SAH", "SAIA", "SAIC", "SAIL", "SANM", "SARO", "SBAC", "SBCF", "SBRA", "SBUX",
    "SCCO", "SCHW", "SCI", "SDRL", "SEB", "SEI", "SEIC", "SEZL", "SF", "SFBS",
    "SFD", "SFM", "SFNC", "SGI", "SHAK", "SHAZ", "SHC", "SHO", "SHOO", "SHW",
    "SIGI", "SIRI", "SITE", "SITM", "SJM", "SKT", "SKWD", "SKY", "SKYW", "SLAB",
    "SLB", "SLDE", "SLG", "SLGN", "SLM", "SLS", "SM", "SMCI", "SMG", "SMMT",
    "SMTC", "SN", "SNA", "SNDK", "SNDR", "SNEX", "SNOW", "SNPS", "SNX", "SO",
    "SOFI", "SOLS", "SOLV", "SON", "SPB", "SPG", "SPGI", "SPHR", "SPSC", "SPXC",
    "SR", "SRCE", "SRE", "SRPT", "SRRK", "SSB", "SSD", "SSMR", "SSNC", "SSRM",
    "ST", "STAG", "STC", "STDN", "STE", "STEP", "STLD", "STOK", "STRL", "STT",
    "STWD", "STZ", "SUI", "SUN", "SUNB", "SUNC", "SUPN", "SWK", "SWKS", "SWX",
    "SXI", "SXT", "SYBT", "SYF", "SYK", "SYM", "SYNA", "SYRE", "SYY", "T",
    "TALO", "TAP", "TARS", "TBBK", "TCBI", "TDC", "TDG", "TDS", "TDW", "TDY",
    "TECH", "TEM", "TENB", "TER", "TEX", "TFC", "TFSL", "TFX", "TGT", "TGTX",
    "THC", "THG", "THO", "TILE", "TJX", "TKO", "TKR", "TLN", "TMDX", "TMO",
    "TMUS", "TNET", "TNGX", "TNL", "TOL", "TOST", "TOWN", "TPC", "TPG", "TPL",
    "TPR", "TR", "TREX", "TRGP", "TRLV", "TRMB", "TRMK", "TRN", "TRNO", "TROW",
    "TRU", "TRV", "TRVI", "TSCO", "TSLA", "TSN", "TTAN", "TTC", "TTD", "TTEK",
    "TTMI", "TTWO", "TVTX", "TW", "TWLO", "TWST", "TXG", "TXN", "TXNM", "TXRH",
    "TXT", "TYL", "U", "UAL", "UBER", "UBSI", "UCB", "UCTT", "UDR", "UE",
    "UEC", "UFPI", "UFPT", "UGI", "UHAL.B", "UHS", "UI", "ULS", "ULTA", "UMBF",
    "UNF", "UNFI", "UNH", "UNIT", "UNM", "UNP", "UPS", "UPST", "URBN", "URGN",
    "URI", "USAC", "USAR", "USB", "USFD", "USLM", "UTHR", "UTZ", "UUUU", "V",
    "VAC", "VC", "VCEL", "VCTR", "VCYT", "VECO", "VEEV", "VERA", "VERX", "VFC",
    "VG", "VIA", "VIAV", "VICI", "VICR", "VIRT", "VISN", "VKTX", "VLO", "VLTO",
    "VLY", "VMC", "VMI", "VMRK", "VNO", "VNOM", "VNT", "VOYA", "VOYG", "VRDN",
    "VRNS", "VRSK", "VRSN", "VRT", "VRTX", "VSAT", "VSEC", "VSH", "VSNT", "VST",
    "VSXY", "VTR", "VTRS", "VVV", "VVX", "VZ", "W", "WAB", "WAFD", "WAL",
    "WAT", "WAY", "WBD", "WBI", "WCC", "WDAY", "WDC", "WDFC", "WEC", "WELL",
    "WERN", "WES", "WEX", "WFC", "WFRD", "WGS", "WH", "WHD", "WHR", "WING",
    "WK", "WLK", "WLY", "WM", "WMB", "WMG", "WMS", "WMT", "WOR", "WPC",
    "WRB", "WRBY", "WSBC", "WSC", "WSFS", "WSM", "WSO", "WST", "WT", "WTFC",
    "WTRG", "WTS", "WTTR", "WULF", "WWD", "WY", "WYNN", "XE", "XEL", "XMTR",
    "XNCR", "XOM", "XPO", "XRAY", "XYL", "XYZ", "YETI", "YOU", "YUM", "Z",
    "ZBH", "ZBIO", "ZBRA", "ZETA", "ZION", "ZM", "ZS", "ZTS", "ZWS", "ZYME",
    "SPY",
]

# Set True once you have full history and just want to top up the last
# ~30 trading days each run instead of re-pulling ~19 years every time --
# much faster and avoids re-downloading data that never changes.
REFRESH_ONLY_RECENT = False
RECENT_DAYS = 40

# Skip a ticker whose CSV already exists (checked before REFRESH_ONLY_RECENT
# logic). Makes a big run resumable after an interruption -- just re-run the
# script. Set False to force a full re-pull of every ticker regardless.
SKIP_EXISTING = True

# Seconds to pause between tickers. yfinance/Yahoo will rate-limit or start
# returning empty data if hit too fast across ~1600 tickers back to back.
SLEEP_BETWEEN = 0.5


def yf_symbol(ticker: str) -> str:
    """Yahoo Finance uses a hyphen for share classes (BRK-B), not a dot."""
    return ticker.replace(".", "-")


def _atomic_to_csv(df, out_path: Path):
    """Write via a temp file + os.replace instead of df.to_csv(out_path) directly.

    to_csv() opens out_path with mode "w", which truncates it to 0 bytes
    before writing a single byte -- if anything else reads this file in that
    window (e.g. the dashboard's app/lib/options_common.py, which globs and
    reads every ticker CSV in this folder to reconstruct live features),
    it can see a truncated/empty file and blow up with pandas'
    EmptyDataError. Writing to a temp file in the SAME directory (so the
    rename is on the same filesystem) and renaming into place is atomic on
    POSIX -- a concurrent reader always sees either the complete old file or
    the complete new one, never a partial one.
    """
    fd, tmp_path = tempfile.mkstemp(dir=out_path.parent, prefix=out_path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            df.to_csv(f, index=False)
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def pull_ticker(ticker: str):
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"{ticker}.csv"
    symbol = yf_symbol(ticker)

    if SKIP_EXISTING and out_path.exists() and not REFRESH_ONLY_RECENT:
        print(f"{ticker}: already have {out_path.name}, skipping (set SKIP_EXISTING=False to force)")
        return

    if REFRESH_ONLY_RECENT and out_path.exists():
        existing = pd.read_csv(out_path, parse_dates=["date"])
        period = f"{RECENT_DAYS}d"
        new = yf.download(symbol, period=period, progress=False, auto_adjust=False)
        new = _clean(new, ticker)
        if new is None:
            return
        combined = pd.concat([existing, new]).drop_duplicates(subset="date", keep="last")
        combined = combined.sort_values("date")
        _atomic_to_csv(combined, out_path)
        print(f"{ticker}: refreshed, {len(combined)} total rows")
    else:
        df = yf.download(symbol, start=START_DATE, progress=False, auto_adjust=False)
        df = _clean(df, ticker)
        if df is None:
            return
        _atomic_to_csv(df, out_path)
        print(f"{ticker}: {len(df)} rows -> {out_path}")


def _clean(df, ticker):
    if df is None or df.empty:
        print(f"{ticker}: no data returned, skipping")
        return None
    df = df.reset_index()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df = df.rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    return df[["date", "open", "high", "low", "close", "volume"]]


def main():
    global REFRESH_ONLY_RECENT
    args = sys.argv[1:]
    if "--refresh-recent" in args:
        REFRESH_ONLY_RECENT = True
        args = [a for a in args if a != "--refresh-recent"]
        print(f"--refresh-recent: topping up the last {RECENT_DAYS} days for each ticker "
              f"(instead of skipping tickers that already have a CSV).")
    tickers = args if args else DEFAULT_UNIVERSE
    if not tickers:
        print("No tickers specified and DEFAULT_UNIVERSE is empty -- "
              "edit this file or pass tickers on the command line.")
        return
    print(f"Pulling {len(tickers)} tickers into {OUT_DIR}/ ...")
    failed = []
    for i, t in enumerate(tickers, 1):
        try:
            pull_ticker(t)
        except Exception as e:
            print(f"{t}: FAILED - {e}")
            failed.append(t)
        if SLEEP_BETWEEN:
            time.sleep(SLEEP_BETWEEN)
        if i % 25 == 0:
            print(f"--- {i}/{len(tickers)} done ---")
    print(f"\nFinished. {len(tickers) - len(failed)}/{len(tickers)} succeeded.")
    if failed:
        print(f"Failed tickers ({len(failed)}): {', '.join(failed)}")
        print("Just re-run the script -- SKIP_EXISTING will skip what already succeeded "
              "and retry only these.")


if __name__ == "__main__":
    main()
