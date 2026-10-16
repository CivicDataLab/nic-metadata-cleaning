"""
Grammar / spelling / clarity fixes for dublin_core_remaining.new_catalog_title.

Applied as the last step of fix_new_catalog_title_remaining.build(), so a re-run
of that script keeps them. RULES are regexes applied to every name in order;
EXACT maps a full name (after RULES) to its corrected form. Smart Cities names
keep the "<Topic> : <City>" shape -- rules that normalise a topic only touch
the part before " : ".
"""

import re

# (pattern, replacement) on the whole name, in order.
RULES = [
    (r"&quot;?", '"'),
    (r"\bnot is use\b", "not in use"),
    (r"\btemporary not in use\b", "temporarily not in use"),
    (r"\bSchedule (Caste|Tribe)s?\b", r"Scheduled \1s"),
    (r"\bServa Shiksha\b", "Sarva Shiksha"),
    (r"\bCharacterstics\b", "Characteristics"),
    (r"(\w)\(", r"\1 ("),                       # "schemes(tanks)" -> "schemes (tanks)"
    (r"\(\s+", "("), (r"\s+\)", ")"),           # "( MSME Registration )"
    (r"\s+,", ","),
    (r",(?=[A-Za-z])", ", "),                   # "PM2.5,PM10" -> "PM2.5, PM10"
    (r"(?<=[A-Za-z)])- (?=[A-Z])", " - "),      # "Programme- Based" -> "Programme - Based"
    (r"(?<=\w) -(?=[A-Z])", " - "),             # "Coal Production -Sector"
    (r"[.\s]+$", ""),                           # trailing full stop
    (r"\s{2,}", " "),
]

# Topic-part rules for the Smart Cities "<Topic> : <City>" names.
TOPIC_RULES = [
    (r"^(COVID|Covid)(\s*-?\s*19|19)?( Datasets)?$", "COVID-19"),
    (r"^(COVID|Covid)(\s*-?\s*19|19)? Details$", "COVID-19 Details"),
    (r"^Covid Bed$", "COVID-19 Beds"),
    (r"^Covid Vaccination", "COVID-19 Vaccination"),
    (r"^Bifurcation of Covid Vaccination$", "Bifurcation of COVID-19 Vaccination"),
    (r"^Citizen Facilit(i)?ation Cent(er|re)s?$", "Citizen Facilitation Centers"),
    (r"^Citizen Facilitation Centers \(Citizen Facilities\)$", "Citizen Facilitation Centers"),
    (r"^Citizens facilities$", "Citizen Facilities"),
    (r"^Community (Facility|facilities)$", "Community Facilities"),
    (r"^Conditions? [Oo]f Roads$", "Condition of Roads"),
    (r"^Budget ?for Open ?[Ss]paces ?[Dd]evelopment$", "Budget for Open Spaces Development"),
    (r"^(Earnings?|Buses Earnings)[- ]*(from )?Bus [Tt]rips?$", "Earnings from Bus Trips"),
    (r"^Earning Bus Trip \(OSRTC\)$", "Earnings from Bus Trips (OSRTC)"),
    (r"^Bus trips earning$", "Earnings from Bus Trips"),
    (r"^Buses Earnings$", "Earnings from Buses"),
    (r"^Digital [Aa]vail(i)?ability$", "Digital Availability"),
    (r"^Digital Payment$", "Digital Payments"),
    (r"^Digital payments \(Commercial\)$", "Digital Payments (Commercial)"),
    (r"^(Dieases|Disease)$", "Diseases"),
    (r"^Diseases data$", "Diseases Data"),
    (r"^Crime$", "Crimes"),
    (r"^Crimes from$", "Crimes"),
    (r"^Cultural : Heritage$", "Cultural Heritage"),
    (r"^Cutural Heritage$", "Cultural Heritage"),
    (r"^City profile$", "City Profile"),
    (r"^Circle rate$", "Circle Rate"),
    (r"^CC TV Cameras$|^CCTV Camera$", "CCTV Cameras"),
    (r"^D2D Collection Coverage$", "Door-to-Door Collection Coverage"),
    (r"^Door to [Dd]oor ", "Door-to-Door "),
    (r"^Electricity - \.$", "Electricity"),
    (r"^Electricty$", "Electricity"),
    (r"^Electricity consumption$", "Electricity Consumption"),
    (r"^Electricity[- ]consumption[- ]by[- ]sub[- ]sector$", "Electricity Consumption by Sub-Sector"),
    (r"^Electricity Consumption By Sub-Sector$", "Electricity Consumption by Sub-Sector"),
    (r"^Environment Advance Pollutant$", "Environment - Advanced Pollutants"),
    (r"^Environment Air Quality$", "Environment - Air Quality"),
    (r"^Environment Pollutants \(NO, NOX, Benzene, Toluene, Oxylene, WS, RH, SR, RG\)$",
     "Environment - Pollutants (NO, NOx, Benzene, Toluene, O-Xylene, WS, RH, SR, RG)"),
    (r"^Ex-Legal Cases$", "Legal Cases"),
    (r"^Ex-Visitors Count At Zoo Complexes$", "Visitor Count at Zoo Complexes"),
    (r"^Fatal road crash$", "Fatal Road Crashes"),
    (r"^Fatalities traffic accidents$", "Traffic Accident Fatalities"),
    (r"^Female Teacher$", "Female Teachers"),
    (r"^Financial [Hh]ealth$", "Financial Health"),
    (r"^Financial Health information$", "Financial Health Information"),
    (r"^Financial literacy campaign$", "Financial Literacy Campaign"),
    (r"^Fire Station$", "Fire Stations"),
    (r"^Forest Area Acc to new work Plan$", "Forest Area According to New Working Plan"),
    (r"^Furniture for Teacher$", "Furniture for Teachers"),
    (r"^Geographical info$", "Geographical Information"),
    (r"^Girls toilet facility in school$", "Girls' Toilet Facility in Schools"),
    (r"^Governance Registered voters$", "Governance - Registered Voters"),
    (r"^Govt Medical College PG Specialization$", "Government Medical College PG Specializations"),
    (r"^Health : Infrastructure$", "Health Infrastructure"),
    (r"^Health Infrast?ructure( Catalog)?$|^Health Infrastucture( Catalog)?$", "Health Infrastructure"),
    (r"^Health Infrastructure MC-owned and Private$", "Health Infrastructure (MC-owned and Private)"),
    (r"^High and Higher Secondary School of Dist$", "High and Higher Secondary Schools of the District"),
    (r"^Hospital with Lab facility$", "Hospitals with Lab Facility"),
    (r"^Hospital with covid beds$", "Hospitals with COVID-19 Beds"),
    (r"^Hospitals Nursing Homes Location$", "Hospitals and Nursing Homes Locations"),
    (r"^House Holds$", "Households"),
    (r"^House hold Details$", "Household Details"),
    (r"^House less population$", "Houseless Population"),
    (r"^Household profile$", "Household Profile"),
    (r"^Households and Property tax$", "Households and Property Tax"),
    # Housing and Slums: one spelling, numbered parts as " - N"
    (r"^Housing (&|and) [Ss]lum[sp]?s?\s*(?:[-:]\s*|\s)?(\d)$", r"Housing and Slums - \2"),
    (r"^Housing (&|and) Slums$|^Housing Slum$|^Housing and Slum$", "Housing and Slums"),
    (r"^Housing (&|and) [Ss]lum [Pp]opulation$|^Housing Slum Population$", "Housing and Slum Population"),
    (r"^Housing & Slums Cricle$", "Housing and Slums - Circle Rates"),
    (r"^Housing & Basic Infrastructure data$", "Housing and Basic Infrastructure Data"),
    (r"^Housing & Slums Infrastructure Distribution$", "Housing and Slums - Infrastructure Distribution"),
    (r"^Housing and Slums Basic Infrastructure Data$", "Housing and Slums - Basic Infrastructure Data"),
    (r"^Housing and Slums Circle Rate$", "Housing and Slums - Circle Rate"),
    # ITC Neighbourhood: one spelling, numbered parts as " - N"
    (r"^ITC ?N[ei]?[ig]?h?bou?r?[hb]?ood", "ITC Neighbourhood"),
    (r"^ITC Neighbourhood\s*(?:\((\d)\)|[-:]\s*(\d)|(\d))$",
     lambda m: "ITC Neighbourhood - " + (m.group(1) or m.group(2) or m.group(3))),
    (r"^ITC Neighbourhood area bifurcation Data$", "ITC Neighbourhood - Area Bifurcation Data"),
    (r"^ITC Neighbourhood Children Facilities Provisions$", "ITC Neighbourhood - Children Facilities Provision"),
    (r"^ITC Neighbourhood budget for open spaces development$",
     "ITC Neighbourhood - Budget for Open Spaces Development"),
    (r"^ITC Neighbourhood (Area|Budget)$", r"ITC Neighbourhood - \1"),
    (r"^ITC Open Dumping grounds$", "ITC Open Dumping Grounds"),
    (r"^ITMS E-challan$", "ITMS E-Challan"),
    (r"^Intake capacity of WTP$", "Intake Capacity of WTP"),
    (r"^Jalau Kasht Utpadan$", "Fuelwood (Jalau Kasht) Production"),
    (r"^Kanmai$", "Tanks (Kanmai)"),
    (r"^Kitchen Shed School$", "School Kitchen Sheds"),
    (r"^Lighting in Streets Public Parks Gardens and Open Spaces$",
     "Lighting in Streets, Public Parks, Gardens and Open Spaces"),
    (r"^List of parks$", "List of Parks"),
    (r"^Literacy rate$", "Literacy Rate"),
    (r"^MC total receipts$", "MC Total Receipts"),
    (r"^Magazines periodicals$", "Magazines and Periodicals"),
    (r"^Mid day meal$", "Mid-Day Meal"),
    (r"^Min max average Water Levels$", "Minimum, Maximum and Average Water Levels"),
    (r"^Mobility infrastructure$", "Mobility Infrastructure"),
    (r"^Mode Of Transport$", "Mode of Transport"),
    (r"^Monthy Ambient Air Quality Report$", "Monthly Ambient Air Quality Report"),
    (r"^Mortality [Rr]ate( 1)?$", "Mortality Rate"),
    (r"^Municipal budget allocation for open spaces and parks$",
     "Municipal Budget Allocation for Open Spaces and Parks"),
    (r"^Municipal council services$", "Municipal Council Services"),
    (r"^Newspapers sale$", "Newspaper Sales"),
    (r"^(No\.? ?[Oo]f|Number [Oo]f) Vehicle Registration$|^No of Vehicle Registered$",
     "Number of Vehicle Registrations"),
    (r"^(No\.? ?[Oo]f|Number [Oo]f) Buses$", "Number of Buses"),
    (r"^No of Houses and Slum population$", "Number of Houses and Slum Population"),
    (r"^Non Notified Slum Area$", "Non-Notified Slum Areas"),
    (r"^Number of hotels and collection$", "Number of Hotels and Collection"),
    (r"^Number of registered person in gst$", "Number of Persons Registered under GST"),
    (r"^Number of water connection from WTP$", "Number of Water Connections from WTP"),
    (r"^Number of workers$", "Number of Workers"),
    (r"^Oorani$", "Ponds (Oorani)"),
    (r"^Open Defection$", "Open Defecation"),
    (r"^Open Space$|^Open spaces$|^Openspace$", "Open Spaces"),
    (r"^Parking lots$", "Parking Lots"),
    (r"^Parks Gardens Open Spaces$", "Parks, Gardens and Open Spaces"),
    (r"^Public Parks Gardens and Open Spaces$", "Public Parks, Gardens and Open Spaces"),
    (r"^Pensioner details$", "Pensioner Details"),
    (r"^Personnel of police department$", "Police Department Personnel"),
    (r"^Police [Ss]tations?$", "Police Stations"),
    (r"^Pre primary sections in school$", "Pre-Primary Sections in Schools"),
    (r"^Primary School of district$", "Primary Schools of the District"),
    (r"^Private unaided Recognized$", "Private Unaided Recognized"),
    (r"^Progress Report GIS based$", "GIS-based Progress Report"),
    (r"^Property Tax MC - \($", "Property Tax (MC)"),
    (r"^Public Toilet Coverage$", "Public Toilets Coverage"),
    (r"^Public [Tt]ransport [Mm]ode ?[Ss]hare$", "Public Transport Mode Share"),
    (r"^Public Transport accessibilities$", "Public Transport Accessibility"),
    (r"^Public transport access$", "Public Transport Access"),
    (r"^Public transport and Other Registered Vehicles$", "Public Transport and Other Registered Vehicles"),
    (r"^Railway station$", "Railway Station"),
    (r"^Rainy days$", "Rainy Days"),
    (r"^Ramps for handycap in school$", "Ramps for Differently-Abled Students in Schools"),
    (r"^Registered Voter$", "Registered Voters"),
    (r"^Registration details$", "Registration Details"),
    (r"^Religious places$", "Religious Places"),
    (r"^Road : Safety$|^Road safety$|^Roadsafety$", "Road Safety"),
    (r"^Road Safety information$", "Road Safety Information"),
    (r"^Road connectivity$", "Road Connectivity"),
    (r"^Roads information$", "Roads Information"),
    (r"^School Between Number of Working Days Primary$", "Number of Working Days in Primary Schools"),
    (r"^School Having Functional Toilet for girls$", "Schools Having Functional Toilets for Girls"),
    (r"^School functional Toilet For Girls$", "School Functional Toilets for Girls"),
    (r"^School Inspected$", "Schools Inspected"),
    (r"^School Pgi and Safety$", "School PGI and Safety"),
    (r"^Schools Established Since$", "Schools by Year of Establishment"),
    (r"^Schools Hand Washing Facility Toilets Urinals$", "Schools with Hand Washing Facilities, Toilets and Urinals"),
    (r"^Schools having Toilet$", "Schools Having Toilets"),
    (r"^Self Help Group$", "Self Help Groups"),
    (r"^Seprate Room For Head Master$", "Separate Room for Head Master"),
    (r"^Services through ICCC$", "Services Through ICCC"),
    (r"^Sew(age|erage) Treatment Plants?$", "Sewage Treatment Plants"),
    (r"^Shop licenses$", "Shop Licences"),
    (r"^Shop and Establishment$", "Shops and Establishments"),
    (r"^Shops And Establishment Licence$", "Shops and Establishments Licence"),
    (r"^Single classroom in school$", "Single-Classroom Schools"),
    (r"^Slum [Hh]ousing and [Pp]opulation( data)?$", "Slum Housing and Population Data"),
    (r"^Solid Waste Collection Equipments$", "Solid Waste Collection Equipment"),
    (r"^Solid Waste Collection Vehicles?$", "Solid Waste Collection Vehicles"),
    (r"^Solid Waste Collection vehicle information$", "Solid Waste Collection Vehicle Information"),
    (r"^Solid Waste (D2D|Door [Tt]o Door|Door2Door) [Cc]ollection$", "Solid Waste Door-to-Door Collection"),
    (r"^Solid Waste (D2D|Door [Tt]o Door|Door2Door) [Cc]ollection Revenue$|^Solid Waste Collection D2D Revenue$",
     "Solid Waste Door-to-Door Collection Revenue"),
    (r"^Solid Waste Generated,? Collected,? Processed Data$", "Solid Waste Generated, Collected and Processed Data"),
    (r"^Solid Waste Management - \.$", "Solid Waste Management"),
    (r"^Solid Waste Management - Seggregation$", "Solid Waste Management - Segregation"),
]

EXACT = {
    # ---- A-E
    "Achievement On National Highways": "Achievements on National Highways",
    "Admin Boundaries": "Administrative Boundaries",
    "Adolescent Girls Following Advices Regarding Health and Hygiene Care Discussed During NHE":
        "Adolescent Girls Following Advice on Health and Hygiene Care Discussed During NHE",
    "Advance Pollutant : Agartala": "Advanced Pollutants : Agartala",
    "Advance air Pollutants : Kakinada": "Advanced Air Pollutants : Kakinada",
    "Environment - Advance Pollutants : Bengaluru": "Environment - Advanced Pollutants : Bengaluru",
    "Age, Sex and Educational level Population, Census 1991 - India and States":
        "Population by Age, Sex and Educational Level, Census 1991 - India and States",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Sagar": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Sagar",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Surat": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Surat",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Udaipur": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Udaipur",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Panaji": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Panaji",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Pune": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Pune",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Saharanpur": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Saharanpur",
    "Air Quality S02, PM2.5, PM10, NO2, O3 : Solapur": "Air Quality (SO2, PM2.5, PM10, NO2, O3) : Solapur",
    "Air Quality So2 PM 2.5, PM10, NO2 : Tumakuru": "Air Quality (SO2, PM2.5, PM10, NO2) : Tumakuru",
    "All India And State-wise Juveniles Delinquency Under IPC Cases":
        "All India And State-wise Juvenile Delinquency Under IPC Cases",
    "All India and State-wise Number Of Cognizable Crime Under IPC And Strength Of Police Force":
        "All India and State-wise Number Of Cognizable Crimes Under IPC And Strength Of Police Force",
    "All other teacher for teaching subject : Ujjain": "All Other Teachers by Teaching Subject : Ujjain",
    "Ambient Air Quality Data for Heavy Metals Lead (Pb) & Nickel (Ni) - Feb : Guwahati":
        "Ambient Air Quality Data for Heavy Metals Lead (Pb) & Nickel (Ni) : Guwahati",
    "Ambient Air Quality Data for Heavy Metals Lead (Pb) & Nickel (Ni) - March : Guwahati":
        "Ambient Air Quality Data for Heavy Metals Lead (Pb) & Nickel (Ni) : Guwahati",
    "Anganwadi and Chreches : Chandigarh": "Anganwadis and Creches : Chandigarh",
    "Annual Plan as percentage to GSDP (Current Prices)": "Annual Plan as Percentage of GSDP (Current Prices)",
    "Approved Outlay State-wise for five years Plan and its annual plans":
        "State-wise Approved Outlay for Five Year Plans and Annual Plans",
    "Area According Year : Ujjain": "Area by Year : Ujjain",
    "Area wise status of Mining Lease distribution (Frequency in Hect)":
        "Area-wise Status of Mining Lease Distribution (Frequency in Hectares)",
    "Area/ Production and Productivity of various kinds of Spices":
        "Area, Production and Productivity of Various Spices",
    "Area / Population And Income Of G-20 Countries": "Area, Population and Income of G-20 Countries",
    "Area / Production And Productivity of Major Fruits and Vegetables Producing Countries In The World":
        "Area, Production and Productivity of Major Fruit and Vegetable Producing Countries in the World",
    "Attendance of the Members of Lok Sabha Session": "Attendance of Members of Lok Sabha by Session",
    "Attendance of the Members of Rajya Sabha for the Session": "Attendance of Members of Rajya Sabha by Session",
    "Average Age of AWWs and distribution of AWW by marital status":
        "Average Age of AWWs and Distribution of AWWs by Marital Status",
    "Average Agricultural Daily Wage Rate Rural in Rupees":
        "Average Daily Agricultural Wage Rate in Rural Areas (in Rupees)",
    "Average Monthly Export & Import Transactions from Major Port":
        "Average Monthly Export & Import Transactions from Major Ports",
    "Average annual expenditure per student of age 529 years in general education":
        "Average annual expenditure per student of age 5-29 years in general education",
    "Average outgoing (Rs.) per outgoing minute (CDMA)": "Average Outgoing Revenue (Rs.) per Outgoing Minute (CDMA)",
    "Average outgoing per outgoing minute (GSM)": "Average Outgoing Revenue per Outgoing Minute (GSM)",
    "Back series of enrollment in class I": "Back Series of Enrolment in Class I",
    "BharatNet Servise Ready Gram Panchayat": "BharatNet Service Ready Gram Panchayats",
    "Block wise Distribution of Shallow Tubewells according to depth of the Dugwells":
        "Block wise Distribution of Shallow Tubewells according to depth of the Shallow Tubewells",
    "Distribution of Shallow Tubewells according to depth of the Dugwell":
        "Distribution of Shallow Tubewells according to depth of the Shallow Tubewells",
    "Boundriwal : Ujjain": "Boundary Wall : Ujjain",
    "Boys toilet facility : Ujjain": "Boys' Toilet Facility : Ujjain",
    "Buses Transport Earnings : Gwalior": "Bus Transport Earnings : Gwalior",
    "Buses transport : Gwalior": "Bus Transport : Gwalior",
    "Buses Public Transport Access : Chandigarh": "Bus Public Transport Access : Chandigarh",
    "Buses Public Transport Accessibility : Shillong": "Bus Public Transport Accessibility : Shillong",
    "Buses OSRTC : Rourkela": "Buses (OSRTC) : Rourkela",
    "Capacity of jails by inmates population": "Capacity of Jails by Inmate Population",
    "Capital Formation By Type Of Assets And BY Type Of Institution At Constant Price":
        "Capital Formation By Type Of Assets And By Type Of Institution At Constant Price",
    "Capital Formation By Type Of Assets And BY Type Of Institution At current Price":
        "Capital Formation By Type Of Assets And By Type Of Institution At Current Price",
    "Cases and their value Of property stolen & recovered": "Cases and Value of Property Stolen & Recovered",
    "Cases registered under IT Act of Cyber crime": "Cyber Crime Cases Registered under IT Act",
    "Cases registered under related sections of Indian Penal Code (IPC) of Cyber Crime":
        "Cyber Crime Cases Registered under Related Sections of Indian Penal Code (IPC)",
    "Cast Wise Enrollment : Ujjain": "Caste-wise Enrolment : Ujjain",
    "Categorization of water borne and vector born diseases : Chandigarh":
        "Categorization of Water-borne and Vector-borne Diseases : Chandigarh",
    "Census houses and the uses": "Census Houses and the Uses to which they are Put",
    "Change in the Forest Cover of States/UT": "Change in the Forest Cover of States/UTs",
    "Actual Change in Forest Cover of States/UT": "Actual Change in Forest Cover of States/UTs",
    "Child need care protection cases : Diu": "Children in Need of Care and Protection : Diu",
    "City profile - Monthly rainfall : Madurai": "City Profile - Monthly Rainfall : Madurai",
    "City Profile - Rainy days : Madurai": "City Profile - Rainy Days : Madurai",
    "City Wifi Usage : Kohima": "City Wi-Fi Usage : Kohima",
    "City and location wise ambient air quality": "City and Location-wise Ambient Air Quality",
    "Classwise enrolment in different categories of schools (Provisional data)":
        "Class-wise Enrolment in Different Categories of Schools (Provisional Data)",
    "Coal Production - Sector": "Sector-wise Coal Production",
    "College per lakh population (18-23 years) and Average enrolment per college":
        "Colleges per Lakh Population (18-23 Years) and Average Enrolment per College",
    "Committed expenditure of the states (Salaries+pensions+Interest payments)":
        "Committed Expenditure of the States (Salaries, Pensions and Interest Payments)",
    "Communities Amenities availability : Puducherry": "Community Amenities Availability : Puducherry",
    "Composition of Revenue-GSM": "Composition of Revenue - GSM",
    "Construction approved plans : Pimpri Chinchwad": "Approved Construction Plans : Pimpri Chinchwad",
    "Consumer category wise sale of power": "Consumer Category-wise Sale of Power",
    "Conversion to NA : Diu": "Conversion to Non-Agricultural (NA) Land : Diu",
    "Country wise India's imports by Principal Commodity": "Country-wise India's Imports by Principal Commodity",
    "Country-wise India Exports by Principal Commodity": "Country-wise India's Exports by Principal Commodity",
    "Crime categorization : Chandigarh": "Crime Categorization : Chandigarh",
    "Crime committed against Senior citizen": "Crimes Committed against Senior Citizens",
    "Crime against Scheduled Castes": "Crimes against Scheduled Castes",
    "Crime against Scheduled Tribes": "Crimes against Scheduled Tribes",
    "Crime committed against Scheduled Castes": "Crimes Committed against Scheduled Castes",
    "Crime committed against Scheduled Tribes": "Crimes Committed against Scheduled Tribes",
    "Crime committed against children under different crime heads":
        "Crimes Committed against Children under Different Crime Heads",
    "Daily Data of Evapo-transpiration": "Daily Data of Evapotranspiration",
    "Demographic Profile Household : Shillong": "Demographic Profile - Household : Shillong",
    "Departure of Rainfall data": "Rainfall Departure Data",
    "Details Poultry Birds in Farms / Hatcheries in Rural and Urban combined (Livestock Census)":
        "Details of Poultry Birds in Farms / Hatcheries in Rural and Urban combined (Livestock Census)",
    "Details of Department Related to Parliamentary Standing Committees of Rajya Sabha":
        "Details of Department Related Parliamentary Standing Committees of Rajya Sabha",
    "Details of Mithun by Age and Sex in Urban and rural combined (Livestock Census)":
        "Details of Mithun by Age and Sex in Rural and Urban combined (Livestock Census)",
    "Details of Toilet : Ujjain": "Details of Toilets : Ujjain",
    "Details of Yaks by Age and Sex Rural and Urban combined (Livestock Census)":
        "Details of Yaks by Age and Sex in Rural and Urban combined (Livestock Census)",
    "Details of financial outlay Department of Agricultural Research and Education":
        "Details of Financial Outlay of Department of Agricultural Research and Education",
    "Details of wages payments of prisoners": "Details of Wage Payments to Prisoners",
    "Discom final : Ujjain": "DISCOM Data : Ujjain",
    "Distribution of School Having Fulfill Teacher ratio : Ujjain":
        "Distribution of Schools Meeting the Teacher Ratio : Ujjain",
    "Distribution of adverse fulfill teachers ratio : Ujjain":
        "Distribution of Schools Not Meeting the Teacher Ratio : Ujjain",
    "District-wise crimes under various sections of Indian Penal Code (IPC) crimes":
        "District-wise Crimes under Various Sections of Indian Penal Code (IPC)",
    "Districts-wise Proposed and Actual Expenditure by Key Sectors - Based on Sample Survey":
        "District-wise Proposed and Actual Expenditure by Key Sectors - Based on Sample Survey",
    "Donkeys, Rabbit and Dogs and Elephants (18th livestock census)":
        "Donkeys, Rabbits, Dogs and Elephants (18th livestock census)",
    "Drains Sewerage : Ujjain": "Drains and Sewerage : Ujjain",
    "Dwelling and Projects Approved-HUDCO": "Dwellings and Projects Approved - HUDCO",
    "EGS/AIE centres - (ISCED-1)": "EGS/AIE Centres (ISCED-1)",
    "Earnings Of Factory Worker": "Earnings of Factory Workers",
    "Economic- Activity wise Active Companies": "Economic Activity-wise Active Companies",
    "Economic- Activity wise Active Government Companies": "Economic Activity-wise Active Government Companies",
    "Economic- Activity wise Active Non-Government Companies":
        "Economic Activity-wise Active Non-Government Companies",
    "Economical and Financial and Taxes : Ajmer": "Economy, Finance and Taxes : Ajmer",
    "Election To The Lok Sabha - House of People": "Election To The Lok Sabha - House of the People",
    "Electric Sub Staions : Rourkela": "Electric Substations : Rourkela",
    "Employments In Ports": "Employment In Ports",
    "Employment exchanges Data": "Employment Exchanges Data",
    "Enrolment of Teacher in training schools": "Enrolment in Teacher Training Schools",
    "Enterpreneurship Profile (Enterprises Owned by)": "Entrepreneurship Profile (Ownership of Enterprises)",
    # ---- E-N
    "Equipments Used in Livestock Sector Rural and Urban combined (Livestock Census)":
        "Equipment Used in Livestock Sector in Rural and Urban combined (Livestock Census)",
    "Estimated Number Of Species By A Various Taxonomic Groups": "Estimated Number of Species by Various Taxonomic Groups",
    "Estimated Reserve and Installed Capacity of Various Sources of Energies":
        "Estimated Reserve and Installed Capacity of Various Sources of Energy",
    "Estimates of Components Nutritional Status of Children Aged 7 Months-60 Months (ICDS v/s Non ICDS)":
        "Estimates of Components of Nutritional Status of Children Aged 7-60 Months (ICDS vs Non-ICDS)",
    "Estimates of Components of NHE-Child Index: Percentage of Mothers Followed the Advices Given by AWW on the Following Components of Child Care":
        "Estimates of Components of NHE-Child Index: Percentage of Mothers Following the Advice Given by AWW on Components of Child Care",
    "Estimates of yield rates, and share of cross breed, non-descript, buffalo and goats in milk production":
        "Estimates of yield rates and share of crossbred, non-descript, buffalo and goats in milk production",
    "Estimates of yield rates, and share of ram/weather, ewe, lamb in wool Production":
        "Estimates of yield rates and share of ram/wether, ewe and lamb in wool production",
    "Evaluation of The Scheme-RGGVY (Rajiv Gandhi Grameen Vidyutikaran Yojana)":
        "Evaluation of the Scheme - RGGVY (Rajiv Gandhi Grameen Vidyutikaran Yojana)",
    "Fauna (Biodiversity Resource) distribution in Centrsl Himalaya":
        "Fauna (Biodiversity Resources) Distribution in Central Himalaya",
    "Flying hours sanction per annum by type of Helicopter on wet lease by North-Eastern State Governments":
        "Flying Hours Sanctioned per Annum by Type of Helicopter on Wet Lease by North-Eastern State Governments",
    "Forest Fire Incidences across all the states of India": "Forest Fire Incidents across All States of India",
    "GDP of India and major Sectors of Economy, Share of each sector to GDP and Growth rate of GDP and other sectors of economy 1951-52 onward":
        "GDP of India and Major Sectors of Economy, Share of Each Sector in GDP and Growth Rate of GDP and Other Sectors of Economy 1951-52 Onwards",
    "Gross Capital Formulation in Agriculture, Forestry and Fishing in the Agriculture and Allied Activities Sector during tenth and eleventh five year plan period":
        "Gross Capital Formation in Agriculture, Forestry and Fishing in the Agriculture and Allied Activities Sector during Tenth and Eleventh Five Year Plan Period",
    "Gross Enrolment Ratio at Primary Upper Primary and Elementary level":
        "Gross Enrolment Ratio at Primary, Upper Primary and Elementary Level",
    "Growth Of Different Kinds Of Colleges And Polytechnics Basd On Art, Medical, Engineering And Technical Courses":
        "Growth of Different Kinds of Colleges and Polytechnics Based on Arts, Medical, Engineering and Technical Courses",
    "ICAR Video gallery Information": "ICAR Video Gallery Information",
    "Impact of ICDS on Colostrums Feeding": "Impact of ICDS on Colostrum Feeding",
    "Index Number of production of Principal Crops": "Index Numbers of Production of Principal Crops",
    "India - Domestic Tourism:NSS": "India - Domestic Tourism: NSS",
    "International Comparisions - Fisheries Statistics 2014": "International Comparisons - Fisheries Statistics 2014",
    "Investigators Observations on about Items of PSE (% AWC)": "Investigators' Observations on Items of PSE (% AWC)",
    "Investigators Observations on Medical Kits (%AWC)": "Investigators' Observations on Medical Kits (% AWC)",
    "Jails wise population of prison inmates": "Jail-wise Population of Prison Inmates",
    "LIST of Ph.D AWARDEES": "List of Ph.D. Awardees",
    "Lactating Mothers Following Advices Regarding Services/Activities about Child Care Discussed During NHE":
        "Lactating Mothers Following Advice on Services/Activities about Child Care Discussed During NHE",
    "List of Ongoing Projects of cost more than 100 crore under NLCPR":
        "List of Ongoing Projects Costing More than Rs 100 Crore under NLCPR",
    "List of organisation of North East state declared unlawful associations under unlawful activities (Prevention) Act, 1967":
        "List of Organisations of North Eastern States Declared Unlawful Associations under the Unlawful Activities (Prevention) Act, 1967",
    "List of field crops varieties hybrids released and notified":
        "List of Field Crop Varieties and Hybrids Released and Notified",
    "Location of aluminum deposits (Bauxite) in India and its salient features":
        "Location of Aluminium (Bauxite) Deposits in India and its Salient Features",
    "Industrial Classification of Main Workers in Manufacturing Processing, Servicing and Repairs by Household Industry and Non-household Industry, Census 2001 - India and States":
        "Industrial Classification of Main Workers in Manufacturing, Processing, Servicing and Repairs by Household Industry and Non-household Industry, Census 2001 - India and States",
    "Major issues discussed in meetings of VEC\\SMCs - Based on Sample Survey":
        "Major issues discussed in meetings of VECs/SMCs - Based on Sample Survey",
    "Month wise quantity of Fortified rice distributed under pilot scheme":
        "Month-wise Quantity of Fortified Rice Distributed under Pilot Scheme",
    "Mortality And Under nutrition Based On NFHS Report": "Mortality and Undernutrition Based on NFHS Report",
    "NBA-Physical and financial progress": "NBA - Physical and Financial Progress",
    "National Expenditure On Researching and Development In Relation To GNP / GDP":
        "National Expenditure On Research and Development In Relation To GNP / GDP",
    "Name of Insurgent groups in North East and their leaders": "Names of Insurgent Groups in North East and their Leaders",
    # ---- N-S
    "Non - Plan Revenue Expenditure (NPRE) and its Components during Eleventh Plan":
        "Non-Plan Revenue Expenditure (NPRE) and its Components during Eleventh Plan",
    "Non Households Enterprises and Institutions Owning Animals/Poultry Birds in Rural and Urban Combined (Livestock Census)":
        "Non-Household Enterprises and Institutions Owning Animals/Poultry Birds in Rural and Urban Combined (Livestock Census)",
    "Non Lapsable Central Pool of resources ongoing projects with funds status":
        "Non-Lapsable Central Pool of Resources - Ongoing Projects with Fund Status",
    "Non Lapsable Central Pool of Resources": "Non-Lapsable Central Pool of Resources",
    "Non-Government Companies struck off - Region/State wise Distribution":
        "Non-Government Companies Struck Off - Region/State-wise Distribution",
    "Number Of Depressions/Deep Deepressions Formed Over The North Indian Ocean":
        "Number Of Depressions/Deep Depressions Formed Over The North Indian Ocean",
    "Number of Allopathic Medical And Dental Colleges And Admission":
        "Number of Allopathic Medical And Dental Colleges And Admissions",
    "Number of Telephones In India": "Number of Telephones in India",
    "Number of field crops varieties released by ICAR": "Number of Field Crop Varieties Released by ICAR",
    "Number of horticultural crops varieties released": "Number of Horticultural Crop Varieties Released",
    "Number of horticultural crops varieties released (based on decade release)":
        "Number of Horticultural Crop Varieties Released (Decade-wise)",
    "Number, membership, income, expenditure and funds of registered trade union":
        "Number, membership, income, expenditure and funds of registered trade unions",
    "Observation on accuracy of maintenance of different records (%AWC)":
        "Observation on Accuracy of Maintenance of Different Records (% AWC)",
    "Offenders Relation And Proximity To Rape Victims": "Offenders' Relation and Proximity to Rape Victims",
    "Out Turn (AISHE Survey)": "Out-Turn (AISHE Survey)",
    "Parents responses on PTA and SSA - Based on Sample Survey": "Parents' Responses on PTA and SSA - Based on Sample Survey",
    "Percentage of AWC have adequacy of space for different type of activities":
        "Percentage of AWCs Having Adequate Space for Different Types of Activities",
    "Percentage of AWC provided types of services reported by AWW":
        "Percentage of AWCs Providing Types of Services Reported by AWW",
    "Percentage of AWC received medical kit": "Percentage of AWCs that Received Medical Kits",
    "Percentage of AWC reported Availability and Utilisation of Medicine":
        "Percentage of AWCs Reporting Availability and Utilisation of Medicine",
    "Percentage of AWC trained adequately to conduct PSE": "Percentage of AWCs Adequately Trained to Conduct PSE",
    "Percentage of AWW Attended Training and Duration (In Days)":
        "Percentage of AWWs Who Attended Training and Duration (In Days)",
    "Percentage of children (aged below 6 year) suffered from the most common diseases":
        "Percentage of Children (Aged Below 6 Years) Suffering from the Most Common Diseases",
    "Percentage of community leader helps in AWC activities": "Percentage of Community Leaders Helping in AWC Activities",
    "Percentage Of Distribution Of Rural And Urban Census Houses According To The Uses To Which They Are Put":
        "Percentage Distribution of Rural and Urban Census Houses According to the Uses to Which They Are Put",
    "Percentage Of Distribution Of Rural And Urban Households By Size Of Dwelling Units Occupied":
        "Percentage Distribution of Rural and Urban Households by Size of Dwelling Units Occupied",
    "Performances of Micro / Small / Medium Enterprises (MSMEs)": "Performance of Micro / Small / Medium Enterprises (MSMEs)",
    "Postal Life Insurance And Rural Postal Life Insurance Polices Issued":
        "Postal Life Insurance And Rural Postal Life Insurance Policies Issued",
    "Pregnant Women Following Advices Regarding Services/Activities about Child Care Discussed During NHE":
        "Pregnant Women Following Advice on Services/Activities about Child Care Discussed During NHE",
    "Pregnant Women Following Advices Regarding Services/Activities about Mother Care Discussed During NHE (%)":
        "Pregnant Women Following Advice on Services/Activities about Mother Care Discussed During NHE (%)",
    "Pupil teacher ratio (PTR)": "Pupil Teacher Ratio (PTR)",
    "R&D projects from other funding agency": "R&D Projects from Other Funding Agencies",
    "Railway Frieght Operation": "Railway Freight Operations",
    "Realisation From Sale of All or Part of The Residual Equity in Disinvested CPSEs /Companies":
        "Realisation From Sale of All or Part of The Residual Equity in Disinvested CPSEs/Companies",
    "Receipts Under Corporation Tax From": "Receipts Under Corporation Tax",
    "Region wise, District Wise, Commodity wise, Daily food stock Position of FCI":
        "Region-wise, District-wise and Commodity-wise Daily Food Stock Position of FCI",
    "Region-wise area of different classes Gulf of Kachchh": "Region-wise Area of Different Classes - Gulf of Kachchh",
    "Region-wise area of different classes Lakshadweep": "Region-wise Area of Different Classes - Lakshadweep",
    "Registered birth and death": "Registered Births and Deaths",
    "Results of high school examination of annual and supplementary examination results":
        "Results of High School Annual and Supplementary Examinations",
    "Results of high school examination of high school open examination board results":
        "Results of High School Open Examination Board",
    "Results of high school examination of opening school": "Results of High School Examination of Open School",
    "Results of higher secondary examination of annual and supplementary examination results":
        "Results of Higher Secondary Annual and Supplementary Examinations",
    "Results of higher secondary examination of higher secondary open school examination board results":
        "Results of Higher Secondary Open School Examination Board",
    "Rooms and Hotels in different Category of Hotels in India":
        "Rooms and Hotels in Different Categories of Hotels in India",
    "SC/ST/rural area enrolment to total enrolment in schools":
        "Share of SC/ST/Rural Area Enrolment in Total Enrolment in Schools",
    "Scheme-wise data pertaining to Direct Benefit Transfer (DBT) for 08 Departments and 43 districts Month-wise":
        "Month-wise and Scheme-wise Data on Direct Benefit Transfer (DBT) for 8 Departments and 43 Districts",
    "Separate programme for 15-45 years women reported by AWW":
        "Separate Programme for Women Aged 15-45 Years Reported by AWW",
    "Service Area wise Access (Wireless +Wireline) Telephone Subscribers":
        "Service Area wise Access (Wireless + Wireline) Telephone Subscribers",
    "Service Area wise Teledensity - Rural, Urban and Total tele-density":
        "Service Area wise Teledensity - Rural, Urban and Total",
    "Service Area wise Wireline Subscribers Base": "Service Area wise Wireline Subscriber Base",
    "Share of enrolment of Girls, SC, STs and CWSN - Based on Sample Survey":
        "Share of enrolment of Girls, SCs, STs and CWSN - Based on Sample Survey",
    "Share of female teachers and SC\\ST teachers in schools - Based on Sample Survey":
        "Share of female teachers and SC/ST teachers in schools - Based on Sample Survey",
    "Share of commercial in total electricity sales": "Share of commercial sector in total electricity sales",
    "Share of revenue from commercial in total electricity sale revenue":
        "Share of revenue from commercial sector in total electricity sales revenue",
    "Share of revenue from industry sector in total electricity sale revenue":
        "Share of revenue from industry sector in total electricity sales revenue",
    "Share of revenue from railway traction in total electricity sale revenue":
        "Share of revenue from railway traction in total electricity sales revenue",
    "Sittings Hours and Time Lost Due to Disruptions or Forced Adjournments in Each Session of Lok Sabha":
        "Sitting Hours and Time Lost Due to Disruptions or Forced Adjournments in Each Session of Lok Sabha",
    "Shape files of Inter-Basin Transfer link": "Shapefiles of Inter-Basin Transfer Links",
}


def _split_city(name):
    """Return (topic, city) for '<Topic> : <City>', else (name, None)."""
    if " : " in name:
        topic, city = name.rsplit(" : ", 1)
        return topic, city
    return name, None


def fix(name):
    if not name:
        return name
    s = name
    for pat, rep in RULES:
        s = re.sub(pat, rep, s)
    topic, city = _split_city(s)
    if city is not None:
        for pat, rep in TOPIC_RULES:
            topic = re.sub(pat, rep, topic)
        s = f"{topic} : {city}"
    s = EXACT.get(s, s)
    return s
