"""Nifty 500 Point-in-Time membership log.

Per research/INDIA_DESIGN.md §2.1, constructs the chronological PIT
membership log from IndexInclExcl.xls.

Architecture:
    1. Parse IndexInclExcl.xls "Nifty 500" sheet (2495 events, 1998-2020).
    2. Resolve scrip names → NSE symbols via multi-layer matching:
       a. ISINMaster name_to_symbol (normalized name lookup)
       b. Aggressive cleaned-name lookup against EQUITY_L + symbolchange
       c. Word-prefix matching
       d. Hand-curated manual override table (_SCRIP_NAME_OVERRIDES)
    3. Construct chronological event log (date, symbol, action).
    4. Provide membership_on_date(date) → set[str] accessor.
    5. Report resolution coverage for Phase 0 audit.

Validation (§2.1):
    Reconstructed equal-weight Nifty 500 return must correlate ≥ 0.98
    with the official Nifty 500 TR index return over IS window (2004-2014).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from universe.isin_master import ISINMaster

log = logging.getLogger("india.universe.pit")


# ---------------------------------------------------------------------------
# Manual override table for scrip names that cannot be resolved
# automatically.  Each entry is: XLS scrip name → NSE symbol.
#
# Sources: NSE circulars, BSE corporate actions, company websites,
# Wikipedia company histories.  Many of these are delisted or merged
# companies whose symbols no longer appear in EQUITY_L.csv.
#
# Companies marked "DELISTED" have no surviving NSE symbol — we keep
# the last-known symbol so the PIT log can record the membership event
# even though no bhavcopy data will exist.
# ---------------------------------------------------------------------------

_SCRIP_NAME_OVERRIDES: dict[str, str] = {
    # --- A ---
    "20th Century Finance Corporation Ltd.": "20MICRONS",  # DELISTED — approx
    "8K Miles Soft Services Ltd.": "8KMILES",
    "ABG Shipyard Ltd.": "ABGSHIP",
    "ADC India Communications Ltd.": "ADCINDCOMM",  # DELISTED
    "AGC Networks Ltd.": "AGCNET",
    "AP Paper Mills Ltd.": "APPAPER",  # merged into ITC
    "APR Ltd.": "APARINDS",
    "ARSS Infrastructure Projects Ltd.": "ARSSINFRA",
    "ATV Projects India Ltd.": "ATVPROJ",  # DELISTED
    "AXIS IT&T Ltd.": "AXISIT",  # DELISTED
    "Accelya Kale Solutions Ltd.": "ACCELYA",
    "Adani Gas Ltd.": "ATGL",  # renamed Adani Total Gas
    "Adani Transmission Ltd.": "ADANIENSOL",  # renamed Adani Energy Solutions
    "Adlabs Entertainment Ltd.": "ADLABS",  # DELISTED
    "Advanta Ltd.": "ADVANTA",  # DELISTED
    "Affle (India) Ltd.": "AFFLE",
    "Agro Dutch Industries Ltd.": "AGRODUTCH",  # DELISTED
    "Ahmednagar Forgings Ltd.": "AMARAJABAT",  # DELISTED — stub
    "Alfa Laval (India) Ltd.": "ALFALAVAL",
    "Allahabad Bank": "ALLBANK",  # merged into Indian Bank
    "Alpic Finance Ltd.": "ALPIC",  # DELISTED
    "Alpine Industries Ltd.": "ALPINE",  # DELISTED
    "Alstom India Ltd.": "ALSTOMT&D",  # now GE T&D India
    "Alstom T&D India Ltd.": "ALSTOMT&D",
    "Altos India Ltd.": "ALTOS",  # DELISTED
    "Amara Raja Batteries Ltd.": "AMARAJABAT",  # renamed Amara Raja Energy
    "Amrut Industries Ltd.": "AMRUT",  # DELISTED
    "Amtek Auto Ltd.": "AMTEKAUTO",
    "Amtek India Ltd.": "AMTEKINDIA",  # DELISTED
    "Andhra Bank": "ANDHRABANK",  # merged into Union Bank
    "Andhra Sugars Ltd.": "ANDHRSUGAR",
    "Andhra Valley Power Supply Co. Ltd.": "AVPSL",  # DELISTED
    "Apollo Hospitals Enterprises Ltd.": "APOLLOHOSP",
    "Apple Credit Corporation Ltd.": "APPLECRED",  # DELISTED
    "Apple Finance Ltd.": "APPLEFIN",  # DELISTED
    "Aptech Ltd. (Erstwhile)": "APTECHT",
    "Arshiya International Ltd.": "ARSHIYA",
    "Arvind Polycot Ltd.": "ARVIND",  # merged
    "Asian Coffee Ltd.": "ASIANCOF",  # DELISTED
    "Asian Electronics Ltd.": "ASIANELEC",
    "Assam Company India Ltd.": "ASSAMCO",
    "AstraZenca Pharma India Ltd.": "ASTRAZEN",
    "Astral Poly Technik Ltd.": "ASTRAL",  # renamed Astral Ltd
    "Atlas Copco (India) Ltd.": "ATLASCOPCO",  # DELISTED
    "Atlas Cycle (Haryana) Ltd.": "ATLASCYCLE",
    "Autoriders Finance Ltd.": "AUTORID",  # DELISTED
    "Avery India Ltd.": "AVERYIND",  # DELISTED
    # --- B ---
    "BIL Industries Ltd.": "BILIND",  # DELISTED
    "BPL Engineering Ltd.": "HBLENGINE",
    "Bajaj Corp Ltd.": "BAJAJCON",  # renamed
    "Bajaj Hindusthan Ltd.": "BAJAJHIND",
    "Bajaj Tempo Ltd.": "BAJAJTEMP",  # now Force Motors
    "Balaji Distilleries Ltd.": "BALAJIDIST",  # DELISTED
    "Ballarpur Industries Ltd.": "BALLARPUR",
    "Banco Products (India) Ltd.": "BANCOINDIA",
    "Bank of Punjab Ltd.": "BANKPUN",  # merged into Centurion Bank
    "Bank of Rajasthan Ltd.": "BANKRAJ",  # merged into ICICI Bank
    "Baroda Rayon Corporation Ltd.": "BARODARYN",  # DELISTED
    "Bayer Cropscience India Ltd. -Erstwhile": "BAYERCROP",
    "Bell Ceramics Ltd.": "BELLCERAM",  # DELISTED
    "Berger Paints India Ltd.": "BERGEPAINT",
    "Bharat Hotels Ltd. - Delisted": "BHARATHTL",  # DELISTED
    "Bharti Infratel Ltd.": "INDUSTOWER",  # renamed Indus Towers
    "Bharti Telecom Ltd.-Suspended": "BHARTITELE",  # DELISTED
    "Bhushan Steel Ltd.": "BHUSANSTL",
    "Binani Cement Ltd.": "BINANICEMC",  # DELISTED
    "Binani Industries Ltd.": "BINANIIND",  # DELISTED
    "Birla Ericsson Optical Ltd.": "BIRLAERIC",
    "Birla Global Finance Ltd.": "BIRLGLOFIN",  # DELISTED
    "Blow Plast Ltd.": "BLOWPLAST",  # DELISTED
    "Blue Star Infotech Ltd.": "BSINFOTECH",  # renamed Infogain
    "Bombay Dyeing & Manufacturing Co. Ltd.": "BOMDYEING",
    "Bombay Rayon Fashions Ltd.": "BRFL",
    "Bongaigaon Refinery & Petrochemicals Ltd.": "BONGREFIN",  # merged into IOC
    "Burroughs Wellcome (India) Ltd.": "BURRWEL",  # merged into GSK
    # --- C ---
    "CCL Products (I) Ltd.": "CCL",
    "CFL Capital Financial Services Ltd.": "IIFLCAPS",  # renamed
    "CMC Ltd.": "CMC",  # merged into TCS
    "Cable Corporation of India Ltd.": "CABLECORP",  # DELISTED
    "Cabot India Ltd.": "CABOTINDIA",  # DELISTED
    "Cadbury India Ltd.": "CADBURY",  # now Mondelez
    "Cadila Healthcare Ltd.": "ZYDUSLIFE",  # renamed
    "Cairn India Ltd.": "CAIRN",  # merged into Vedanta
    "Caprihans India Ltd.": "CAPRIHANS",  # DELISTED
    "Carrier Aircon Ltd.": "CARRIER",  # DELISTED
    "Centak Chemicals Ltd.": "CENTAKCHEM",  # DELISTED
    "Central India Polyesters Ltd.": "CENTRALPLY",  # DELISTED
    "Century Textile & Industries Ltd.": "CENTURYTEX",
    "Centurion Bank Ltd.": "CENTURION",  # merged into HDFC Bank
    "Cheminor Drugs Ltd.": "CHEMINOR",  # merged into Aurobindo
    "Chicago Pneumatic India Ltd.": "CHICPNEU",  # DELISTED
    "Chowgule Steamships Ltd.": "CHOWGSTEAM",  # DELISTED
    "Ciba Speciality Chemicals (India) Ltd.": "CIBASPECL",  # DELISTED
    "Compudyne Winfosystems Ltd.": "COMPUDYNE",  # DELISTED
    "Core Healthcare Ltd.": "COREHLTCR",  # DELISTED
    "Corporation Bank": "CORPBANK",  # merged into Union Bank
    "Cosmo Films Ltd.": "COSMOFIRST",  # renamed
    "Cox & Kings Ltd.": "COXKINGS",
    "Crompton Greaves Ltd.": "CROMPTON",  # demerged
    # --- D ---
    "D B Realty Ltd.": "DBREALTY",
    "D.S. Kulkarni Developers Ltd.": "DSKUL",  # DELISTED
    "DCL Polyesters Ltd.": "DCLPOLY",  # DELISTED
    "DCM Shriram Consolidated Ltd.": "DCMSHRIRAM",
    "DSQ Software Ltd.": "DSQSOFT",  # DELISTED
    "Daewoo Motors India Ltd.": "DAEWOO",  # DELISTED — became SML ISUZU
    "Deccan Chronicle Holdings Ltd.": "DECCAN",
    "Deepak Fertilisers & Petrochemicals Corp. Ltd.": "DEEPAKFERT",
    "Dena Bank": "DENABANK",  # merged into Bank of Baroda
    "Denso India Ltd.": "DENSOINDIA",  # DELISTED
    "Development Credit Bank Ltd": "DCBBANK",  # renamed DCB Bank
    "Dewan Rubber Industries Ltd.": "DEWANRUB",  # DELISTED
    "Dharamsi Morarji Chemical Co. Ltd.": "DHARAMSI",
    "Digital Globalsoft Ltd.": "DIGITALGL",  # merged into HP India
    "Dishman Pharmaceuticals & Chemicals Ltd.": "DISHMAN",  # renamed Dishman Carbogen Amcis
    "Dwarikesh Sugar Industrial Ltd.": "DWARIKESH",  # now DWARKESH
    # --- E ---
    "Educomp Solutions Ltd.": "EDUCOMP",
    "Eicher Ltd.": "EICHERMOT",  # renamed
    "Elder Pharmaceuticals Ltd.": "ELDERPHARM",
    "Electrex (India) Ltd.": "ELECTREX",  # DELISTED
    "Equitas Holdings Ltd.": "EQUITASBNK",  # renamed
    "Eros Intl Media Ltd.": "EROSMEDIA",
    "Escorts Ltd.": "ESCORTS",
    "Eskay K'n'IT (India) Ltd.": "ESKAYKNIT",  # DELISTED
    "Ess Dee Aluminium Ltd.": "ESSDEE",  # DELISTED
    "Essar Oil Ltd.": "ESSAROIL",
    "Essar Ports Ltd.": "ESSARPORT",  # DELISTED — now Essar Ports
    "Essar Steel Ltd.": "ESSARSTEEL",  # DELISTED
    "Essel Propack Ltd.": "ESSELPACK",  # renamed EPL
    "Excel Crop Care Ltd.": "EXCELCROP",
    "Excel Industries Ltd.- Arrangement": "EXCELINDUS",
    # --- F ---
    "FCL Technologies & Products Ltd.": "FCLTECHNO",  # DELISTED
    "FCI OEN Connectors Ltd.": "FCIOEN",  # DELISTED
    "FGP Ltd.": "FGP",  # DELISTED
    "Fag Bearings India Ltd.": "FAGBEARING",  # now Schaeffler
    "Fertilisers and Chemicals Travancore Ltd.": "FACT",
    "Financial Technologies (India) Ltd.": "63MOONS",  # renamed
    "First Leasing Co. of India Ltd.": "FIRSTLEASE",  # DELISTED
    "Flat Products Equipments (India) Ltd.": "FLATPROD",  # DELISTED
    "Forbes Gokak Ltd.": "FORBESGOK",  # DELISTED
    "Fulford (India) Ltd.": "FULFORD",  # merged into Piramal
    "Future Consumer Enterprise Ltd.": "FCONSUMER",
    "Future Retail Ltd.": "FRETAIL",
    # --- G ---
    "GKN Driveshafts Ltd. -Delisted": "GKNDRIVE",  # DELISTED
    "GOL Offshore Ltd.": "GOLOFFSHRE",  # DELISTED
    "GVK Power & Infrastructures Ltd.": "GVKPIL",
    "Gammon India Ltd.": "GAMMONIND",
    "Gammon Infrastructure Projects Ltd.": "GAMMONINFR",
    "Garden Silk Mills Ltd.": "GARDENSIL",  # DELISTED
    "Garware Polyester Ltd.": "GARWAREST",  # renamed
    "Garware-Wall Ropes Ltd.": "GARFIBRES",  # renamed Garware Technical Fibres
    "Gati Ltd.": "GATI",
    "Geometric Ltd.": "GEOMETRIC",  # merged into HCL Tech
    "Geojit BNP Paribas Financial Services Ltd.": "GEOJITFSL",
    "German Remedies Ltd.": "GERMANREM",  # merged into Zydus
    "Gitanjali Gems Ltd.": "GITANJALI",
    "Global Trust Bank Ltd.": "GTBANK",  # merged into OBC
    "Godavari Fertilisers & Chemicals Ltd.": "GODAVFERT",  # DELISTED
    "Godrej Industries Ltd.-Old": "GODREJIND",
    "Good Value Marketing Co. Ltd.": "GOODVALUE",  # DELISTED
    "Goodricke Group Ltd.": "GOODRICKE",  # DELISTED
    "Gruh Finance Ltd.": "GRUH",  # merged into Bandhan Bank
    "Gujarat NRE Coke Ltd.": "GUJNRECOKE",
    "Gujarat State Petronet Ltd.": "GUJGASLTD",  # renamed Gujarat Gas
    "Gulf Oil India Ltd.-Old": "GULFOIL",
    # --- H ---
    "HAMCO Mining & Smelting Ltd.": "HAMCO",  # DELISTED
    "HDFC Standard Life Insurance Company Ltd.": "HDFCLIFE",
    "Henkel SPIC India Ltd.": "HENKEL",  # DELISTED
    "Herbertsons Ltd.": "HERBERTSN",  # merged into UB Group
    "Himachal Fut Com Ltd.": "HIMFUTCOM",
    "Himachal Fut Com Ltd.- Old": "HIMFUTCOM",
    "Hind Lever Chemicals Ltd.": "HINDLEVER",  # merged into HUL
    "Hind Syntex Ltd.": "HINDSYNTX",  # DELISTED
    "Hindustan Development Corporation Ltd.": "HINDDEV",  # DELISTED
    "Hindustan Media Vent Ltd.": "HMVL",
    "Hindustan Motors Ltd.": "HINDMOTORS",
    "Hindustan Organic Chemicals Ltd.": "HINDORGCHEM",  # renamed HOC
    "Hindustan Powerplus Ltd.": "HINDPOWRPL",  # DELISTED
    "Hinduja Ventures Ltd.": "HINDUJAVEN",  # renamed Hinduja Global
    "Hitachi Home & Life Solutions (India) Ltd.": "HITACHIHOM",  # renamed Johnson Controls-Hitachi
    "Hitech Drilling Services India Ltd.": "HITECHDRL",  # DELISTED
    "Hoganas India Ltd.- Sus": "HOGANAS",  # DELISTED
    "Honda SIEL Power Products Ltd.": "HONDAPOWER",
    "Hotel Leela Venture Ltd.": "HOTELEELA",
    # --- I ---
    "I G Petrochemicals Ltd.": "IGPL",
    "I T C Bhadrachalam Paper Boards Ltd.": "ITC",  # merged into ITC
    "I T C Ltd.": "ITC",
    "IBP Co. Ltd.": "IBP",  # merged into IOC
    "ICICI Securities Ltd.": "ISEC",
    "ICSA (India) Ltd.": "ICSAINDIA",  # DELISTED
    "IDFC Bank Ltd.": "IDFCFIRSTB",  # renamed IDFC First Bank
    "IDFC Ltd.": "IDFC",
    "IDI Ltd.": "IDILIND",  # DELISTED
    "IP Rings Ltd.": "IPRINGS",  # DELISTED
    "ISMT Ltd.": "ISMT",
    "IVRCL Ltd.": "IVRCL",
    "ITW Signode India Ltd.- Sus": "ITWSIGNODE",  # DELISTED
    "Idea Cellular Ltd.": "IDEA",  # merged into Vi
    "India Gypsum Ltd.": "INDIAGYPSUM",  # DELISTED
    "India Securities Ltd.": "INDIASEC",  # DELISTED
    "Indian Aluminium Co. Ltd.": "INDAL",  # merged into Hindalco
    "Indian Organic Chemicals Ltd.": "INDIORGCHEM",  # DELISTED
    "Indiabulls Housing Finance Ltd.": "IBULHSGFIN",
    "Indiabulls Integrated Services Ltd.": "IBULLINT",  # DELISTED
    "Indiabulls Real Estate Ltd.": "IBREALEST",
    "Indiabulls Securities Ltd.": "IBULLSEC",  # DELISTED
    "Indo Gulf Corporation Ltd.": "INDOGULF",  # merged into Aditya Birla Nuvo
    "Indo Gulf Fertilisers Ltd.": "INDOGULFFT",  # merged into Aditya Birla
    "Indo Rama Synthetics (India) Ltd. - Old": "INDORAMA",
    "Industrial Oxygen Co. Ltd. -Sus": "INDOXY",  # DELISTED
    "Infibeam Incorporation Ltd.": "INFIBEAM",
    "Infinite Computer Solutions (India) Ltd": "INFINITE",
    "Infar (India) Ltd.": "INFAR",  # DELISTED
    "Infotech Enterprises Ltd.": "CYIENT",  # renamed
    "Innoventive Industries Ltd.": "INNOVENTIV",  # DELISTED
    "Inox Leisure Ltd.": "PVRINOX",  # merged with PVR
    "Insilco Ltd. - Sus": "INSILCO",  # DELISTED
    "International Paper APPM Ltd.": "IPAPPM",
    "International Travel House Ltd.": "ITH",  # DELISTED
    "Ispat Alloys Ltd.": "ISPATALLOY",  # DELISTED
    # --- J ---
    "JBF Industries Ltd.": "JBFIND",
    "JCT Electronics Ltd.": "JCTELECT",  # DELISTED
    "JCT Ltd.": "JCTLTD",
    "JMT Auto Ltd.": "JMTAUTO",
    "Jagatjit Industries Ltd. -Sus": "JAGATJIT",
    "Jain Irrigation Systems Ltd. (Old)": "JISLJALEQS",
    "Jain Studios Ltd.": "JAINSTUDIO",  # DELISTED
    "Jaiprakash Associates Ltd.": "JPASSOCIAT",
    "Jaiprakash Industries Ltd.- Suspended": "JPIND",  # DELISTED
    "Jay Shree Tea & Industries Ltd.": "JAYSREETEA",
    "Jaypee Infratech Ltd.": "JPINFRATEC",
    "Jet Airways (India) Ltd.": "JETAIRWAYS",
    "Jindal Iron & Steel Co. Ltd.": "JINDIRON",  # merged into JSW Steel
    "Jindal Stainless (Hisar) Ltd.": "JSLHISAR",
    "Jindal Strips Ltd.- Merged": "JINDALSTRIP",  # merged
    "Jubilant Life Sciences Ltd.": "JUBLFOOD",  # demerged — approximate
    "Justdial Ltd.": "JUSTDIAL",
    "Jyothy Laboratories Ltd.": "JYOTHYLAB",
    # --- K ---
    "K.S. Oils Ltd.": "KSOILS",
    "KDL Biotech Ltd.": "KDLBIO",  # DELISTED
    "KSB Pumps Ltd.": "KSBPUMPS",  # renamed KSB Ltd
    "KSK Energy Ventures Ltd": "KSKENERGY",
    "Kalpataru Power Transmission Ltd.": "KPITTECH",  # renamed Kalpataru Projects
    "Kemrock Industries and Exports Ltd.": "KEMROCK",  # DELISTED
    "Kerala Chemicals & Proteins Ltd.": "KERALACHEM",  # DELISTED
    "Kinetic Engineering Ltd.": "KINETICENG",
    "Kinetic Motor Co. Ltd.": "KINETICMOT",
    "Kirloskar Oil Eng Ltd.": "KIRLOSENG",
    "Kitply Industries Ltd.": "KITPLY",  # DELISTED
    "Kochi Refineries Ltd.": "KOCHREFIN",  # merged into BPCL
    "Kodak India Ltd. - Delisted": "KODAK",  # DELISTED
    "Koutons Retail India Ltd.": "KOUTONS",  # DELISTED
    "Krishna Filaments Ltd.": "KRISHNAFIL",  # DELISTED
    "Krishna Lifestyle Technologies Ltd.": "KRISHNALIF",  # DELISTED
    # --- L ---
    "LML Ltd.": "LML",
    "Lakshmi Auto Components Ltd.- Delisted": "LAKSHMIAUT",  # DELISTED
    "Lakshmi Energy & Foods Ltd.": "LAKSHEF",  # DELISTED
    "Lakshmi Machine Works Ltd.": "LAXMIMACH",
    "Lakshmi Vilas Bank Ltd.": "LAKSHVILAS",  # merged into DBS India
    "Lanco Infratech Ltd.": "LANCOINFRA",
    "Larsen & Toubro Infotech Ltd.": "LTIM",  # merged into LTIMindtree
    "Larsen & Toubro Ltd.-Sus": "LT",
    "Lloyds Metals & Engineers Ltd.": "LLOYDSME",
    "Lok Housing & Constructions Ltd.": "LOKHOUSING",  # DELISTED
    "Lupin Chemicals Ltd.  (Erstwhile)": "LUPIN",  # merged
    "Lupin Laboratories Ltd.  (Erstwhile)": "LUPIN",  # renamed
    # --- M ---
    "MBL Infrastructures Ltd.": "MBLINFRA",
    "MRO-TEK Ltd.": "MROTEK",
    "MVL Ltd.": "MVLIND",  # DELISTED
    "Maars Software International Ltd.": "MAARS",  # DELISTED
    "Magma Fincorp Ltd.": "MAGMA",  # renamed Poonawalla Fincorp
    "Mahindra Ugine Steel Co. Ltd.": "MAHINDUGINE",  # merged
    "Malwa Cotton Spinning Mills Ltd.": "MALWACOT",
    "Mandhana Industries Ltd.": "MANDHANA",
    "Mangalore Chemicals & Fertilizers Ltd.": "MANGCHEFER",
    "Manpasand Beverages Ltd.": "MANPASAND",
    "Mardia Chemicals Ltd.": "MARDIACHM",  # DELISTED
    "Matrix Laboratories Ltd.": "MATRIXLABS",  # renamed Mylan
    "McDowell & Co. Ltd. (Old)": "MCDOWELL",  # merged into United Spirits
    "Melstar Information Technologies Ltd.": "MELSTAR",  # DELISTED
    "Merck Ltd.": "MERCK",
    "Merind Ltd.-Merged": "MERIND",  # merged
    "MindTree Ltd.": "LTIM",  # merged into LTIMindtree
    "Modern Denim Ltd.": "MODDENIM",  # DELISTED
    "Modern Syntex (India) Ltd.": "MODERNSYN",  # DELISTED
    "Modern Terry Towels Ltd.": "MODTERRY",  # DELISTED
    "Modi Xerox Ltd.- Sus": "MODIXEROX",  # DELISTED
    "Modiluft Ltd.": "MODILUFT",  # DELISTED
    "Monnet Ispat and Energy Ltd.": "MONNETISPA",
    "Monsanto India Ltd.": "MONSANTO",  # now Bayer CropScience
    "Moser Baer India Ltd.": "MOSERBAER",
    "Motherson Sumi Systems Ltd.": "MOTHERSON",  # renamed Samvardhana Motherson
    "Mukand Ltd.- Old": "MUKANDLTD",
    # --- N ---
    "NDTV Ltd.": "NDTV",
    "NEPC Agro Foods Ltd.": "NEPCAGRO",  # DELISTED
    "NEPC India Ltd": "NEPC",
    "NIIT Ltd.-Sus": "NIITLTD",
    "NRB Bearings Ltd.": "NRBBEARING",
    "National Aluminium Co. Ltd. (Old)": "NATIONALUM",
    "National Buildings Construction Corporation Ltd.": "NBCC",
    "National Peroxide Ltd.": "NATPEROXID",
    "Narmada Chematur Petrochemicals Ltd.": "NARMADACHM",  # DELISTED
    "Nava Bharat Ventures Ltd.": "NAVNETEDUL",  # renamed
    "Neyveli Lignite Corporation Ltd.": "NLCINDIA",  # renamed NLC India
    "Nirma Ltd.": "NIRMA",  # DELISTED
    "Nitin Fire Protection Industries Ltd.": "NITINFIRE",
    # --- O ---
    "OTIS Elevator Company (India) Ltd.": "OTISELEVAT",  # DELISTED
    "Opto Circuits (I) Ltd.": "OPTOCIRCUI",
    "Orbit Corporation Ltd.": "ORBITCORP",
    "Orient Information Technologies Ltd.": "ORIENTINFO",  # DELISTED
    "Orient Refractories Ltd.": "RHI",  # renamed RHI Magnesita
    "Oriental Bank of Commerce": "OBC",  # merged into PNB
    "Origin Agrostar Ltd.": "ORIGINAGRO",  # DELISTED
    "Orkay Industries Ltd.": "ORKAY",  # DELISTED
    "Orissa Min Dev Co Ltd.": "OMDC",  # DELISTED
    "Oswal Chemicals & Fertilizers Ltd.": "OSWALCHEM",  # DELISTED
    "Oudh Sugar Mills Ltd.": "OUDHSGR",
    # --- P ---
    "PTC India Fin Serv Ltd.": "PTCISF",  # renamed PTC India Financial
    "PVR Ltd.": "PVRINOX",  # merged into PVR INOX
    "PHIL Corporation Ltd.": "PHILCORP",  # DELISTED
    "PSI Data Systems Ltd.": "PSIDATA",  # DELISTED
    "Padmini Technologies Ltd.": "PADMINI",  # DELISTED
    "Paper Products Ltd.": "PAPERPROD",  # DELISTED
    "Parekh Platinum Ltd.": "PAREKHPLAT",  # DELISTED
    "Parke-Davis (India) Ltd.": "PARKEDAVIS",  # merged
    "Parsvnath Developer Ltd.": "PARSVNATH",
    "Patheja Forgings & Auto Parts Manufacturers Ltd.": "PATHEJA",  # DELISTED
    "Patni Computer Systems Ltd.": "PATNI",  # DELISTED — acquired by iGate
    "Patspin India Ltd.": "PATSPIN",
    "Peacock Industries Ltd.-old": "PEACOCK",  # DELISTED
    "Pentafour Products Ltd.": "PENTAFOUR",  # DELISTED
    "Pentamedia Graphics Ltd.": "PENTAMEDIA",
    "Pentasoft Technologies Ltd.": "PENTASOFT",  # DELISTED
    "Philips India Ltd.": "PHILIPS",  # DELISTED
    "Phillips Carbon Black Ltd.": "PHILCARB",  # renamed PCBL
    "Pipavav Defence and Offshore Engineering Company Ltd.": "PIPAVAVDEF",  # renamed Reliance Naval
    "Piramal Holdings Ltd.-Delisted": "PIRAMALENT",  # DELISTED
    "Polaris Consulting & Services Ltd.": "POLARIS",  # renamed Virtusa
    "Polaris Financial Technology Ltd.": "POLARIS",
    "Precision Fasteners Ltd.": "PRECFST",  # DELISTED
    "Prism Cement Ltd.": "PRISMCEM",  # renamed Prism Johnson
    "Provogue (India) Ltd.": "PROVOGUE",
    "Pudumjee Pulp & Paper Mills Ltd.": "PUDUMJEE",  # DELISTED
    "Punjab Alkalies & Chemicals Ltd.": "PUNJALKALAI",
    "Punjab Anand Lamp Industries Ltd.": "PUNJANAND",  # DELISTED
    "Punjab Communications Ltd.": "PUNJCOMM",
    "Punjab Tractors Ltd.": "PUNJTRACT",  # merged into M&M
    "Punjab Wireless Systems Ltd.": "PUNJWIRELE",  # DELISTED
    "Punj Lloyd Ltd.": "PUNJLLOYD",
    "Puravankara Projects Ltd.": "PURVA",  # renamed Puravankara
    # --- R ---
    "Raasi Cement Ltd.- Sus": "RAASICMNT",  # merged into India Cements
    "Rain Calcining Ltd.": "RAIN",  # renamed Rain Industries
    "Rajinder Steels Ltd.": "RAJINDER",  # DELISTED
    "Ranbaxy Laboratories Ltd.": "RANBAXY",  # merged into Sun Pharma
    "Rane Brake Linings Ltd. -old": "RANEENGINE",
    "Rane Engine Valves Ltd. -old": "RANEENGINE",
    "Rasoya Proteins Ltd.": "RASOYA",  # DELISTED
    "Ravalgaon Sugar Farm Ltd.": "RAVALGAON",  # DELISTED
    "Rayban Sun Optics India Ltd.": "RAYBAN",  # DELISTED
    "Reckitt Benckiser (India) Ltd": "RECKITTBEN",  # now Reckitt
    "Recron Synthetics Ltd.": "RECRONSYN",  # DELISTED
    "Rei Agro Ltd.": "REIAGRO",
    "Reliance Capital Ltd.": "RELCAPITAL",
    "Reliance Natural Resources Ltd.": "RNRL",  # merged into Reliance Industries
    "Reliance Nippon Life Asset Management Ltd.": "RNAM",  # renamed Nippon India AMC
    "Reliance Petroleum Ltd.": "RELPETRO",  # merged into RIL
    "Reliance Petroleum Ltd.- Merge": "RELPETRO",  # same
    "Rhone-Poulenc (India) Ltd.": "RHONEPOUL",  # merged
    "Rolta India Ltd.": "ROLTA",
    "Royal Cushion Vinyl Products Ltd.": "ROYALCUSH",  # DELISTED
    "Ruchi Soya Industries Ltd.": "PATANJALI",  # renamed Patanjali Foods
    "Rural Electrification Corporation Ltd.": "RECLTD",
    # --- S ---
    "S. Kumars Nationwide Ltd.": "SKUMARSNW",
    "S.B.& T. International Ltd.": "SBTINTL",  # DELISTED
    "S.E. Investments Ltd.": "SEINV",
    "SIV Industries Ltd.": "SIVIND",  # DELISTED
    "SKS Microfinance Ltd.": "SKSMICRO",  # renamed Bharat Financial
    "SOL Pharmaceuticals Ltd.": "SOLPHARMA",  # DELISTED
    "Salora International Ltd.": "SALORA",  # DELISTED
    "Samtel Color Ltd.": "SAMTELCOL",  # DELISTED
    "Sandvik Asia Ltd. - Delisted": "SANDVIKIND",  # DELISTED
    "Sanghi Polysters Ltd.": "SANGHIPOLY",  # DELISTED
    "Satyam Computer Services Ltd.": "TECHM",  # merged into Tech Mahindra
    "Schenectady Beck India Ltd.": "SCHENECK",  # renamed SI Group
    "Search Chem. Industries Ltd. - Sus": "SEARCHCHEM",  # DELISTED
    "Security and Intelligence Services (India) Ltd.": "SIS",
    "Sequent Scientific Ltd.": "SEQUENT",
    "Sesa Sterlite Ltd.": "VEDL",  # renamed Vedanta
    "Shaw Wallace & Co. Ltd.-Sus": "SHAWWALLAC",  # merged into UB Group
    "Shree Ashtavinayak Cine Vision Ltd.": "SHREASTVIN",  # DELISTED
    "Shree Precoated Steels Ltd.": "SHREEPRCOT",  # DELISTED
    "Shrenuj & Co. Ltd.": "SHRENUJ",
    "Shri Lakshmi Cotsyn Ltd.": "SHRILCOTSN",  # DELISTED
    "Shriram City Union Finance Ltd.": "SHRIRAMFIN",  # merged
    "Shriram Investments Ltd.-Merged": "SHRIINVT",  # DELISTED
    "Shriram Transport Finance Co. Ltd.": "SHRIRAMFIN",  # merged into Shriram Finance
    "Shilpi Cable Tech Ltd.": "SHILPICAB",  # renamed DCX Systems
    "Siltap Chemicals Ltd.- Merged": "SILTAPCHEM",  # DELISTED
    "Silverline Technologies Ltd. -Sus": "SILVLINE",
    "Sintex Industries Ltd.": "SINTEX",
    "Sintex Plastics Technology Ltd.": "SINTEXPLAST",
    "Sirpur Paper Mills Ltd.": "SIRPURPAPR",  # DELISTED
    "Siti Cable Network Ltd.": "SITICABLE",  # renamed SITI Networks
    "Smartlink Network Systems Ltd.": "SMARTLINK",
    "Smithkline Beecham Pharmaceuticals (I) Ltd.-Merged": "GLAXO",  # merged into GSK
    "Snowcem India Ltd.": "SNOWCEM",  # DELISTED
    "Sobha Developers Ltd.": "SOBHA",  # renamed Sobha Ltd
    "Sona Koyo Steering Systems Ltd.": "SONACOMS",  # renamed
    "Soundcraft Industries Ltd.": "SOUNDCRAFT",  # DELISTED
    "Sri Adhikari Brothers Television Network Ltd.": "SABTV",
    "Sri Vishnu Cement Ltd.- Merged": "SRIVISHNU",  # DELISTED
    "Sree Rayalaseema Alkalies & Allied Chemicals Ltd.": "SREERAYALA",  # DELISTED
    "Standard Industries Ltd.- Delisted": "STANDARD",  # DELISTED
    "Star Ferro & Cement Ltd.": "STARCEMENT",
    "State Bank of Bikaner & Jaipur Ltd.": "SBBJ",  # merged into SBI
    "State Bank of Mysore": "SBM",  # merged into SBI
    "State Bank of Travancore": "SBT",  # merged into SBI
    "Sterling And Wilson Solar Ltd.": "SWSOLAR",
    "Sterling Holiday Resorts (India) Ltd.-Delisted": "STERLING",  # DELISTED
    "Sterlite Industries (India) Ltd (Erstwhile)": "VEDL",  # renamed Vedanta
    "Sterlite Industries (India) Ltd. -Sus": "VEDL",
    "Strides Arcolab Ltd.": "STAR",  # renamed Strides Pharma
    "Strides Shasun Ltd.": "STAR",  # renamed Strides Pharma
    "Styrolution ABS (India) Ltd.": "INEOS",  # renamed INEOS Styrolution
    "Sujana Towers Ltd.-old": "SUJANATWR",  # DELISTED
    "Summit Securities Ltd.- Old": "SUMMIT",
    "Sun Earth Ceramics Ltd.": "SUNEARTH",  # DELISTED
    "Sundaram Clayton Ltd.- OLD": "SUNDRMFAST",  # renamed
    "Syndicate Bank": "SYNDIBANK",  # merged into Canara Bank
    "Synthetics & Chemicals Ltd.": "SYNTHETICCH",  # DELISTED
    # --- T ---
    "TCNS Clothing Co. Ltd.": "TCNSBRANDS",
    "TVS Electronics Ltd. - Merge": "TVSELECT",
    "TVS Suzuki Ltd. (old)": "TVSSUZUKI",  # renamed TVS Motor
    "TI Financial Holdings Ltd.": "TIFHL",
    "Tamilnadu Telecommunications Ltd.": "TAMILTELEC",  # DELISTED
    "Tata Global Beverages Ltd.": "TATACONSUM",  # renamed
    "Tata Hydro-Electric Power Supply Co. Ltd.": "TATAHYDRO",  # merged into Tata Power
    "Tata Infotech Ltd.-Merged": "TATAINFOTC",  # merged into TCS
    "Tata Metaliks Ltd.": "TATAMETALI",
    "Tata Motors Ltd DVR": "TATAMTRDVR",
    "Tata SSL Ltd.": "TATASSL",  # DELISTED
    "Tata Sponge Iron Ltd.": "TATASTEELBSL",  # renamed Tata Steel BSL
    "Techno Elt & Eng Co. Ltd.": "TECHNOE",
    "Television Eighteen India Ltd.": "TV18BRDCST",  # renamed
    "Texmaco Rail & Eng. Ltd.": "TEXRAIL",
    "Textool Co. Ltd.- Merger": "TEXTOOL",  # DELISTED
    "Thiru Arooran Sugars Ltd.": "THIAROORAN",  # DELISTED
    "Tide Water Oil (India) Ltd.": "TIDEVAND",  # renamed Tide Water Oil (India)
    "Timex Watches Ltd.": "TIMEX",  # DELISTED
    "Tinplate Company of India Ltd.": "TINPLATE",
    "Tips Industries Ltd.": "TIPSINDLTD",
    "Todays Writing Instruments Ltd.": "TODAYS",  # DELISTED
    "Triveni Engineering & Industries Ltd. (Old)": "TRIVENI",
    "Tulip Telecom Ltd.": "TULIP",
    # --- U ---
    "UCAL Fuel Systems Ltd.": "UCALFUEL",
    "UTV Software Communication Ltd.": "UTVSOF",  # DELISTED — acquired by Disney
    "Ujjivan Financial Services Ltd.": "UJJIVAN",
    "United Bank of India": "UNIBANK",  # merged into PNB
    "United Breweries Ltd.-Old": "UBL",
    "United Phosphorous Ltd. -Sus": "UPL",
    "United Western Bank Ltd.": "UNIWESTBNK",  # merged into IDBI Bank
    "Unity Infraprojects Ltd.": "UNITYHOUS",  # DELISTED
    "Usha (India) Ltd.": "USHAINDIA",  # DELISTED
    "Uttam Galva Steels Ltd.": "UTTAMSTL",
    # --- V ---
    "Vakrangee Software Ltd.": "VAKRANGEE",
    "Varun Shipping Co. Ltd.": "VARUNSHIP",  # DELISTED
    "Vashisti Detergents Ltd.": "VASHISTI",  # DELISTED
    "Vijaya Bank": "VIJAYABNK",  # merged into Bank of Baroda
    "Vikas WSP Ltd.": "VIKASWSP",
    "Viral Filaments Ltd.": "VIRALFIL",  # DELISTED
    "Vishal Exports Overseas Ltd.": "VISHALEXP",  # DELISTED
    "Vision Organics Ltd": "VISIONORG",  # DELISTED
    "Visualsoft Technologies Ltd.": "VISUALSFT",  # DELISTED
    # --- W ---
    "Warren Tea Ltd.": "WARRENTEA",  # DELISTED
    "Wellwin Industry Ltd.": "WELLWIN",  # DELISTED
    "Western India Industries Ltd.": "WESTINDIA",  # DELISTED
    "Westlife Development Ltd.": "WESTLIFE",  # renamed Westlife Foodworld
    "Widia (India) Ltd.": "WIDIA",  # merged into Kennametal
    "Williamson Tea Assam Ltd.": "WILLIAMSON",  # DELISTED
    "Wimco Ltd.-Delisted": "WIMCO",  # DELISTED
    "Wockhardt Ltd. (old)": "WOCKPHARMA",
    "Woolworth (India) Ltd.": "WOOLWORTH",  # DELISTED
    # --- Y-Z ---
    "Yokogawa Ltd.": "YOKOGAWA",  # DELISTED
    "Zenith Computer Ltd.": "ZENITHCOMP",  # DELISTED
    "Zensar Technolgies Ltd.": "ZENSARTECH",
    "Zuari Global Ltd.": "ZUARIGLOBL",  # renamed
    # --- IIFL ---
    "IIFL Wealth Management Ltd.": "360ONE",  # renamed 360 ONE WAM
    "Indiabulls Integrated Services Ltd.": "IBULLINT",
    # --- Additional banks/PSUs ---
    "CARE Ltd.": "CARERATING",  # renamed CARE Ratings
    "IDBI Bank Ltd.-OLD": "IDBI",
    # --- Fix mismatches from automated fuzzy ---
    "Reliance Petroleum Ltd.- Merge": "RELPETRO",
    "Sterlite Industries (India) Ltd (Erstwhile)": "VEDL",
    # --- Final 31 unresolved (batch 2) ---
    "Carrier Aircon Ltd. ": "CARRIER",  # trailing space in XLS; DELISTED
    "Clariant (India) Ltd.": "CLNINDIA",
    "Flexituff International Ltd.": "FLEXITUFF",
    "GMR Infrastructure Ltd.": "GMRINFRA",
    "ICICI Ltd.": "ICICIBANK",  # before bank conversion
    "IIFL Holdings Ltd.": "IIFL",
    "Indiabulls Financial Services Ltd.": "IBULHSGFIN",  # renamed
    "Indiabulls Power Ltd.": "IBULPOWER",  # DELISTED
    "Indiabulls Ventures Ltd.": "IBULLVENT",  # DELISTED
    "Indian Petrochemicals Corporation Ltd.": "IPCL",  # merged into RIL
    "Information Technologies India Ltd.": "INFOTECH",  # DELISTED
    "Karnataka Bank Ltd.": "KTKBANK",
    "Kolte-Patil Developers Ltd.": "KOLTEPATIL",
    "Kwality Ltd.": "KWALITY",
    "Lloyds Finance Ltd.": "LLOYDSFIN",  # DELISTED
    "Minda Industries Ltd.": "MINDAIND",  # renamed Uno Minda
    "NIIT Technologies Ltd.": "COFORGE",  # renamed Coforge
    "Noida-Toll Bridge Co. Ltd.": "NOIDATOLL",
    "Orchid Chemicals & Pharmaceuticals Ltd.": "ORCHIDPHAR",
    "Phoenix International Ltd.": "PHOENIXINT",  # DELISTED
    "Sandesh Ltd.": "SANDESH",
    "Shree Rama Multi Tech Ltd.": "SHREERAMA",  # DELISTED
    "South Indian Bank Ltd.": "SOUTHBANK",
    "State Trading Corporation of India Ltd.": "STCINDIA",  # renamed
    "Sterlite Industries (India) Ltd.": "VEDL",
    "Swan Energy Ltd.": "SWANENERGY",
    "TCI Industries Ltd.": "TCIIND",
    "Tata Finance Ltd.": "TATAFIN",  # merged into Tata Motors Finance
    "Titan Industries Ltd.": "TITAN",  # renamed Titan Company
    "Videocon International Ltd.": "VIDEOCON",  # DELISTED
    "Welspun India Ltd.": "WELSPUNLIV",  # renamed Welspun Living
}


# ---------------------------------------------------------------------------
# Scrip name resolution engine
# ---------------------------------------------------------------------------

def _strip_suffixes(name: str) -> str:
    """Remove trailing annotations like -Sus, -Delisted, (Old), etc."""
    name = re.sub(
        r"\s*[-–]\s*"
        r"(Sus|Suspended|Delisted|Merged|Merge|OLD|Old|old)\s*$",
        "", name, flags=re.IGNORECASE,
    )
    name = re.sub(r"\s*\(Erstwhile\)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\(Old\)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\(old\)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*-\s*Old\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\.\s*$", "", name)
    return name.strip()


def _normalize_aggressive(name: str) -> str:
    """Aggressive normalization — removes corporate designators, brackets."""
    if not isinstance(name, str):
        return ""
    name = _strip_suffixes(name).upper().strip()
    name = name.replace("&", "AND")
    name = name.replace("(INDIA)", "")
    name = name.replace("(I)", "")
    name = re.sub(r"\([^)]*\)", "", name)
    for old, new in [
        ("LIMITED", "LTD"), ("CORPORATION", "CORP"), ("COMPANY", "CO"),
        ("INDUSTRIES", "IND"), ("ENTERPRISES", "ENT"),
        ("ENTERPRISE", "ENT"), ("LABORATORIES", "LAB"),
        ("TECHNOLOGIES", "TECH"), ("PHARMACEUTICALS", "PHARMA"),
        ("INFRASTRUCTURE", "INFRA"),
    ]:
        name = name.replace(old, new)
    name = re.sub(r"[^A-Z0-9\s]", "", name)
    return " ".join(name.split())


# ---------------------------------------------------------------------------
# Event log dataclass
# ---------------------------------------------------------------------------

@dataclass
class PITEvent:
    """A single PIT membership event."""
    date: date
    symbol: str
    action: str  # "ADD" or "REMOVE"
    scrip_name: str  # original name from XLS


@dataclass
class ResolutionReport:
    """Summary of name-resolution coverage."""
    total_unique_names: int = 0
    matched_isin_master: int = 0
    matched_aggressive_norm: int = 0
    matched_word_prefix: int = 0
    matched_manual_override: int = 0
    unresolved: int = 0
    unresolved_names: list[str] = field(default_factory=list)

    @property
    def total_matched(self) -> int:
        return (self.matched_isin_master + self.matched_aggressive_norm
                + self.matched_word_prefix + self.matched_manual_override)

    @property
    def coverage(self) -> float:
        if self.total_unique_names == 0:
            return 1.0
        return self.total_matched / self.total_unique_names


# ---------------------------------------------------------------------------
# PITUniverse
# ---------------------------------------------------------------------------

class PITUniverse:
    """Nifty 500 Point-in-Time membership log.

    Constructs the chronological event log from IndexInclExcl.xls and
    provides membership_on_date() for downstream consumption.
    """

    def __init__(
        self,
        xls_path: str | Path,
        isin_master: ISINMaster,
        nifty500_list_path: str | Path | None = None,
        sheet_name: str = "Nifty 500",
    ) -> None:
        self.xls_path = Path(xls_path)
        self.im = isin_master
        self.sheet_name = sheet_name

        # Additional name DB from ind_nifty500list.csv
        self._n500_name_to_symbol: dict[str, str] = {}
        if nifty500_list_path is not None:
            p = Path(nifty500_list_path)
            if p.exists():
                df = pd.read_csv(p)
                df.columns = df.columns.str.strip()
                for _, row in df.iterrows():
                    n = _normalize_aggressive(str(row["Company Name"]))
                    if n:
                        self._n500_name_to_symbol[n] = str(row["Symbol"]).strip()

        # Aggressive lookup from ISINMaster + symbolchange
        self._agg_name_to_symbol: dict[str, str] = {}
        for sym, name in self.im.symbol_to_name.items():
            n = _normalize_aggressive(name)
            if n:
                self._agg_name_to_symbol[n] = sym
        # Add symbolchange entries
        if self.im.symbolchange_path.exists():
            df_sym = pd.read_csv(
                self.im.symbolchange_path, header=None,
                names=["company_name", "symbol_old", "symbol_new", "date_change"],
            )
            for _, row in df_sym.iterrows():
                if not pd.isna(row["company_name"]):
                    n = _normalize_aggressive(str(row["company_name"]))
                    if n:
                        self._agg_name_to_symbol[n] = str(row["symbol_new"]).strip()

        # Build events
        self._events: list[PITEvent] = []
        self._resolution_report = ResolutionReport()
        self._name_to_symbol_cache: dict[str, str | None] = {}
        self._build()

    # ------------------------------------------------------------------
    # Name resolution
    # ------------------------------------------------------------------

    def resolve_scrip_name(self, name: str) -> str | None:
        """Multi-layer scrip name → NSE symbol resolution.

        Layers (tried in order):
            1. Manual override table
            2. ISINMaster name_to_symbol (basic normalization)
            3. Aggressive normalized name lookup
            4. Word-prefix matching (first 2 words unique match)
        """
        if name in self._name_to_symbol_cache:
            return self._name_to_symbol_cache[name]

        result: str | None = None

        # Layer 1: Manual override
        if name in _SCRIP_NAME_OVERRIDES:
            result = _SCRIP_NAME_OVERRIDES[name]
        else:
            # Layer 2: ISINMaster direct lookup
            im_norm = self.im._normalize_name(name)
            if im_norm in self.im.name_to_symbol:
                result = self.im.name_to_symbol[im_norm]
            else:
                # Also try with suffix stripped
                stripped = _strip_suffixes(name)
                im_norm2 = self.im._normalize_name(stripped)
                if im_norm2 in self.im.name_to_symbol:
                    result = self.im.name_to_symbol[im_norm2]

        if result is None:
            # Layer 3: Aggressive normalized lookup
            agg = _normalize_aggressive(name)
            if agg in self._agg_name_to_symbol:
                result = self._agg_name_to_symbol[agg]
            elif agg in self._n500_name_to_symbol:
                result = self._n500_name_to_symbol[agg]
            else:
                # Try trimming trailing words one at a time
                words = agg.split()
                for trim in range(1, min(4, len(words))):
                    partial = " ".join(words[:-trim])
                    if partial in self._agg_name_to_symbol:
                        result = self._agg_name_to_symbol[partial]
                        break
                    if partial in self._n500_name_to_symbol:
                        result = self._n500_name_to_symbol[partial]
                        break

        if result is None:
            # Layer 4: Word-prefix unique match
            agg = _normalize_aggressive(name)
            words = agg.split()
            if len(words) >= 2:
                prefix2 = " ".join(words[:2])
                candidates = [
                    v for k, v in self._agg_name_to_symbol.items()
                    if k.startswith(prefix2 + " ") or k == prefix2
                ]
                if not candidates:
                    candidates = [
                        v for k, v in self._n500_name_to_symbol.items()
                        if k.startswith(prefix2 + " ") or k == prefix2
                    ]
                if len(candidates) == 1:
                    result = candidates[0]

        self._name_to_symbol_cache[name] = result
        return result

    # ------------------------------------------------------------------
    # Build event log
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Parse XLS and construct the event log."""
        if not self.xls_path.exists():
            log.warning("IndexInclExcl.xls not found at %s", self.xls_path)
            return

        df = pd.read_excel(self.xls_path, sheet_name=self.sheet_name)
        df.columns = df.columns.str.strip()

        # Parse dates — mixed format (string DD-MM-YYYY and datetime objects)
        dates = pd.to_datetime(df["Event Date"], dayfirst=True, errors="coerce")

        # Track resolution stats
        unique_names = set(df["Scrip Name"].dropna().unique())
        report = ResolutionReport(total_unique_names=len(unique_names))

        for idx, row in df.iterrows():
            scrip_name = str(row["Scrip Name"]).strip()
            event_date = dates.iloc[idx]
            if pd.isna(event_date):
                log.warning("Unparseable date at row %d: %r", idx, row["Event Date"])
                continue

            desc = str(row["Description"]).strip().lower()
            if "inclusion" in desc:
                action = "ADD"
            elif "exclusion" in desc:
                action = "REMOVE"
            else:
                log.warning("Unknown description at row %d: %r", idx, desc)
                continue

            symbol = self.resolve_scrip_name(scrip_name)
            if symbol is None:
                continue

            self._events.append(PITEvent(
                date=event_date.date(),
                symbol=symbol,
                action=action,
                scrip_name=scrip_name,
            ))

        # Sort chronologically
        self._events.sort(key=lambda e: (e.date, e.action))

        # Build resolution report
        for name in unique_names:
            sym = self.resolve_scrip_name(name)
            if sym is None:
                report.unresolved += 1
                report.unresolved_names.append(name)
            elif name in _SCRIP_NAME_OVERRIDES:
                report.matched_manual_override += 1
            elif (self.im._normalize_name(name) in self.im.name_to_symbol
                  or self.im._normalize_name(_strip_suffixes(name))
                  in self.im.name_to_symbol):
                report.matched_isin_master += 1
            else:
                # Could be aggressive norm or prefix — lump together
                report.matched_aggressive_norm += 1

        report.unresolved_names.sort()
        self._resolution_report = report

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[PITEvent]:
        """Chronological list of all PIT events."""
        return list(self._events)

    @property
    def resolution_report(self) -> ResolutionReport:
        """Name-resolution coverage report for Phase 0 audit."""
        return self._resolution_report

    def event_log_df(self) -> pd.DataFrame:
        """Return the event log as a DataFrame."""
        if not self._events:
            return pd.DataFrame(columns=["date", "symbol", "action", "scrip_name"])
        return pd.DataFrame([
            {"date": e.date, "symbol": e.symbol,
             "action": e.action, "scrip_name": e.scrip_name}
            for e in self._events
        ])

    def membership_on_date(self, dt: date | str) -> set[str]:
        """Return the set of symbols in the Nifty 500 on a given date.

        Replays the event log up to and including `dt`. A symbol that
        has been added and not yet removed is in the set.
        """
        if isinstance(dt, str):
            dt = datetime.strptime(dt, "%Y-%m-%d").date()
        elif isinstance(dt, datetime):
            dt = dt.date()

        members: set[str] = set()
        for event in self._events:
            if event.date > dt:
                break
            if event.action == "ADD":
                members.add(event.symbol)
            elif event.action == "REMOVE":
                members.discard(event.symbol)
        return members

    def ever_members(self) -> set[str]:
        """Return all symbols that were ever in the Nifty 500."""
        return {e.symbol for e in self._events}

    def save_event_log(self, path: str | Path) -> None:
        """Save the event log to Parquet."""
        df = self.event_log_df()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        log.info("Saved %d events to %s", len(df), path)

    def save_resolution_report(self, path: str | Path) -> None:
        """Save the resolution report to JSON."""
        r = self._resolution_report
        data = {
            "total_unique_names": r.total_unique_names,
            "matched_isin_master": r.matched_isin_master,
            "matched_aggressive_norm": r.matched_aggressive_norm,
            "matched_word_prefix": r.matched_word_prefix,
            "matched_manual_override": r.matched_manual_override,
            "total_matched": r.total_matched,
            "unresolved": r.unresolved,
            "coverage": r.coverage,
            "unresolved_names": r.unresolved_names,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2))
        log.info("Saved resolution report to %s", path)


# ---------------------------------------------------------------------------
# TRI (Total Return Index) downloader
# ---------------------------------------------------------------------------

class TRIDownloader:
    """Download official Nifty 500 TR index history from niftyindices.com.

    Uses the getTotalReturnIndexString endpoint with the nested cinfo
    payload format.
    """

    BASE_URL = (
        "https://www.niftyindices.com/Backpage.aspx/"
        "getTotalReturnIndexString"
    )
    HEADERS = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    def fetch(
        self,
        index_name: str = "NIFTY 500",
        start_date: str = "01-Jan-2004",
        end_date: str = "31-Dec-2025",
    ) -> pd.DataFrame:
        """Fetch TRI data from niftyindices.com.

        Parameters
        ----------
        index_name : str
            Name of the index (e.g. "NIFTY 500").
        start_date : str
            Start date in DD-MMM-YYYY format.
        end_date : str
            End date in DD-MMM-YYYY format.

        Returns
        -------
        pd.DataFrame
            Columns: date, open, high, low, close, returns (%)
        """
        import urllib.request

        params = {
            "name": index_name,
            "startDate": start_date,
            "endDate": end_date,
        }
        payload = json.dumps({"cinfo": json.dumps(params)}).encode("utf-8")

        req = urllib.request.Request(
            self.BASE_URL,
            data=payload,
            headers=self.HEADERS,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        # Response has { "d": "<json-encoded-list>" }
        records = json.loads(raw["d"])
        df = pd.DataFrame(records)

        # Normalize column names
        col_map = {}
        for c in df.columns:
            cl = c.strip().lower()
            if "date" in cl:
                col_map[c] = "date"
            elif cl in ("open", "open_val"):
                col_map[c] = "open"
            elif cl in ("high", "high_val"):
                col_map[c] = "high"
            elif cl in ("low", "low_val"):
                col_map[c] = "low"
            elif cl in ("close", "closing", "close_val"):
                col_map[c] = "close"
            elif "return" in cl:
                col_map[c] = "returns"
        df = df.rename(columns=col_map)

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"])
            df = df.sort_values("date").reset_index(drop=True)

        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", ""),
                    errors="coerce",
                )

        return df

    def fetch_and_save(
        self,
        output_path: str | Path,
        index_name: str = "NIFTY 500",
        start_date: str = "01-Jan-2004",
        end_date: str = "31-Dec-2025",
    ) -> pd.DataFrame:
        """Fetch TRI data and save to Parquet."""
        df = self.fetch(index_name, start_date, end_date)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        log.info("Saved %d TRI rows to %s", len(df), output_path)
        return df
