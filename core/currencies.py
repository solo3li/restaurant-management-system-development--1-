"""
قائمة أشهر 100 عملة في العالم مع التسميات والرموز باللغتين العربية والإنجليزية
مخصصة لنظام المطاعم وفروع الكول سنتر ومساعد الذكاء الاصطناعي.
"""
from typing import Dict, Any, List, Tuple

CURRENCIES_DATA: Dict[str, Dict[str, str]] = {
    # العملات العربية ومنطقة الشرق الأوسط وشمال أفريقيا (أولوية)
    "EGP": {"name_ar": "جنيه مصري", "name_en": "Egyptian Pound", "symbol_ar": "ج.م", "symbol_en": "EGP"},
    "SAR": {"name_ar": "ريال سعودي", "name_en": "Saudi Riyal", "symbol_ar": "ر.س", "symbol_en": "SAR"},
    "AED": {"name_ar": "درهم إماراتي", "name_en": "UAE Dirham", "symbol_ar": "د.إ", "symbol_en": "AED"},
    "KWD": {"name_ar": "دينار كويتي", "name_en": "Kuwaiti Dinar", "symbol_ar": "د.ك", "symbol_en": "KWD"},
    "QAR": {"name_ar": "ريال قطري", "name_en": "Qatari Riyal", "symbol_ar": "ر.ق", "symbol_en": "QAR"},
    "BHD": {"name_ar": "دينار بحريني", "name_en": "Bahraini Dinar", "symbol_ar": "د.ب", "symbol_en": "BHD"},
    "OMR": {"name_ar": "ريال عماني", "name_en": "Omani Rial", "symbol_ar": "ر.ع", "symbol_en": "OMR"},
    "JOD": {"name_ar": "دينار أردني", "name_en": "Jordanian Dinar", "symbol_ar": "د.أ", "symbol_en": "JOD"},
    "IQD": {"name_ar": "دينار عراقي", "name_en": "Iraqi Dinar", "symbol_ar": "د.ع", "symbol_en": "IQD"},
    "LBP": {"name_ar": "ليرة لبنانية", "name_en": "Lebanese Pound", "symbol_ar": "ل.ل", "symbol_en": "LBP"},
    "SYP": {"name_ar": "ليرة سورية", "name_en": "Syrian Pound", "symbol_ar": "ل.س", "symbol_en": "SYP"},
    "LYD": {"name_ar": "دينار ليبي", "name_en": "Libyan Dinar", "symbol_ar": "د.ل", "symbol_en": "LYD"},
    "TND": {"name_ar": "دينار تونسي", "name_en": "Tunisian Dinar", "symbol_ar": "د.ت", "symbol_en": "TND"},
    "DZD": {"name_ar": "دينار جزائري", "name_en": "Algerian Dinar", "symbol_ar": "د.ج", "symbol_en": "DZD"},
    "MAD": {"name_ar": "درهم مغربي", "name_en": "Moroccan Dirham", "symbol_ar": "د.م", "symbol_en": "MAD"},
    "SDG": {"name_ar": "جنيه سوداني", "name_en": "Sudanese Pound", "symbol_ar": "ج.س", "symbol_en": "SDG"},
    "YER": {"name_ar": "ريال يمني", "name_en": "Yemeni Rial", "symbol_ar": "ر.ي", "symbol_en": "YER"},
    "MRU": {"name_ar": "أوقية موريتانية", "name_en": "Mauritanian Ouguiya", "symbol_ar": "أ.م", "symbol_en": "MRU"},
    "SOS": {"name_ar": "شلن صومالي", "name_en": "Somali Shilling", "symbol_ar": "ش.ص", "symbol_en": "SOS"},
    "DJF": {"name_ar": "فرنك جيبوتي", "name_en": "Djiboutian Franc", "symbol_ar": "ف.ج", "symbol_en": "DJF"},
    "KMF": {"name_ar": "فرنك قمري", "name_en": "Comorian Franc", "symbol_ar": "ف.ق", "symbol_en": "KMF"},
    "ILS": {"name_ar": "شيكل", "name_en": "Shekel", "symbol_ar": "₪", "symbol_en": "ILS"},

    # كبرى العملات العالمية
    "USD": {"name_ar": "دولار أمريكي", "name_en": "US Dollar", "symbol_ar": "$", "symbol_en": "$"},
    "EUR": {"name_ar": "يورو", "name_en": "Euro", "symbol_ar": "€", "symbol_en": "€"},
    "GBP": {"name_ar": "جنيه إسترليني", "name_en": "British Pound", "symbol_ar": "£", "symbol_en": "£"},
    "JPY": {"name_ar": "ين ياباني", "name_en": "Japanese Yen", "symbol_ar": "¥", "symbol_en": "¥"},
    "CHF": {"name_ar": "فرنك سويسري", "name_en": "Swiss Franc", "symbol_ar": "CHF", "symbol_en": "CHF"},
    "CAD": {"name_ar": "دولار كندي", "name_en": "Canadian Dollar", "symbol_ar": "C$", "symbol_en": "C$"},
    "AUD": {"name_ar": "دولار أسترالي", "name_en": "Australian Dollar", "symbol_ar": "A$", "symbol_en": "A$"},
    "CNY": {"name_ar": "يوان صيني", "name_en": "Chinese Yuan", "symbol_ar": "¥", "symbol_en": "¥"},
    "INR": {"name_ar": "روبية هندية", "name_en": "Indian Rupee", "symbol_ar": "₹", "symbol_en": "₹"},
    "TRY": {"name_ar": "ليرة تركية", "name_en": "Turkish Lira", "symbol_ar": "₺", "symbol_en": "₺"},
    "RUB": {"name_ar": "روبل روسي", "name_en": "Russian Ruble", "symbol_ar": "₽", "symbol_en": "₽"},
    "BRL": {"name_ar": "ريال برازيلي", "name_en": "Brazilian Real", "symbol_ar": "R$", "symbol_en": "R$"},
    "ZAR": {"name_ar": "راند جنوب أفريقي", "name_en": "South African Rand", "symbol_ar": "R", "symbol_en": "R"},

    # أوروبا
    "SEK": {"name_ar": "كرونة سويدية", "name_en": "Swedish Krona", "symbol_ar": "kr", "symbol_en": "kr"},
    "NOK": {"name_ar": "كرونة نرويجية", "name_en": "Norwegian Krone", "symbol_ar": "kr", "symbol_en": "kr"},
    "DKK": {"name_ar": "كرونة دنماركية", "name_en": "Danish Krone", "symbol_ar": "kr", "symbol_en": "kr"},
    "PLN": {"name_ar": "زلوتي بولندي", "name_en": "Polish Zloty", "symbol_ar": "zł", "symbol_en": "zł"},
    "CZK": {"name_ar": "كرونة تشيكية", "name_en": "Czech Koruna", "symbol_ar": "Kč", "symbol_en": "Kč"},
    "HUF": {"name_ar": "فورنت مجري", "name_en": "Hungarian Forint", "symbol_ar": "Ft", "symbol_en": "Ft"},
    "RON": {"name_ar": "ليو روماني", "name_en": "Romanian Leu", "symbol_ar": "lei", "symbol_en": "lei"},
    "BGN": {"name_ar": "ليف بلغاري", "name_en": "Bulgarian Lev", "symbol_ar": "лв", "symbol_en": "лв"},
    "HRK": {"name_ar": "كونا كرواتية", "name_en": "Croatian Kuna", "symbol_ar": "kn", "symbol_en": "kn"},
    "RSD": {"name_ar": "دينار صربي", "name_en": "Serbian Dinar", "symbol_ar": "дин", "symbol_en": "din"},
    "ISK": {"name_ar": "كرونة آيسلندية", "name_en": "Icelandic Krona", "symbol_ar": "kr", "symbol_en": "kr"},
    "ALL": {"name_ar": "ليك ألباني", "name_en": "Albanian Lek", "symbol_ar": "Lek", "symbol_en": "Lek"},
    "BAM": {"name_ar": "مارك بوسني", "name_en": "Bosnian Mark", "symbol_ar": "KM", "symbol_en": "KM"},
    "MKD": {"name_ar": "دينار مقدوني", "name_en": "Macedonian Denar", "symbol_ar": "ден", "symbol_en": "den"},
    "BYN": {"name_ar": "روبل بيلاروسي", "name_en": "Belarusian Ruble", "symbol_ar": "Br", "symbol_en": "Br"},
    "UAH": {"name_ar": "هريفنيا أوكرانية", "name_en": "Ukrainian Hryvnia", "symbol_ar": "₴", "symbol_en": "₴"},
    "GEL": {"name_ar": "لاري جورجي", "name_en": "Georgian Lari", "symbol_ar": "₾", "symbol_en": "₾"},
    "AMD": {"name_ar": "درام أرميني", "name_en": "Armenian Dram", "symbol_ar": "֏", "symbol_en": "֏"},
    "AZN": {"name_ar": "مانات أذربيجاني", "name_en": "Azerbaijani Manat", "symbol_ar": "₼", "symbol_en": "₼"},

    # آسيا والمحيط الهادئ
    "SGD": {"name_ar": "دولار سنغافوري", "name_en": "Singapore Dollar", "symbol_ar": "S$", "symbol_en": "S$"},
    "HKD": {"name_ar": "دولار هونغ كونغ", "name_en": "Hong Kong Dollar", "symbol_ar": "HK$", "symbol_en": "HK$"},
    "NZD": {"name_ar": "دولار نيوزيلندي", "name_en": "New Zealand Dollar", "symbol_ar": "NZ$", "symbol_en": "NZ$"},
    "KRW": {"name_ar": "وون كوري جنوبي", "name_en": "South Korean Won", "symbol_ar": "₩", "symbol_en": "₩"},
    "IDR": {"name_ar": "روبية إندونيسية", "name_en": "Indonesian Rupiah", "symbol_ar": "Rp", "symbol_en": "Rp"},
    "MYR": {"name_ar": "رينغيت ماليزي", "name_en": "Malaysian Ringgit", "symbol_ar": "RM", "symbol_en": "RM"},
    "THB": {"name_ar": "بات تايلاندي", "name_en": "Thai Baht", "symbol_ar": "฿", "symbol_en": "฿"},
    "PHP": {"name_ar": "بيزو فلبيني", "name_en": "Philippine Peso", "symbol_ar": "₱", "symbol_en": "₱"},
    "VND": {"name_ar": "دونغ فيتنامي", "name_en": "Vietnamese Dong", "symbol_ar": "₫", "symbol_en": "₫"},
    "PKR": {"name_ar": "روبية باكستانية", "name_en": "Pakistani Rupee", "symbol_ar": "₨", "symbol_en": "₨"},
    "BDT": {"name_ar": "تاكا بنغلاديشية", "name_en": "Bangladeshi Taka", "symbol_ar": "৳", "symbol_en": "৳"},
    "LKR": {"name_ar": "روبية سريلانكية", "name_en": "Sri Lankan Rupee", "symbol_ar": "Rs", "symbol_en": "Rs"},
    "NPR": {"name_ar": "روبية نيبالية", "name_en": "Nepalese Rupee", "symbol_ar": "Rs", "symbol_en": "Rs"},
    "MMK": {"name_ar": "كيات ميانماري", "name_en": "Myanmar Kyat", "symbol_ar": "K", "symbol_en": "K"},
    "KHR": {"name_ar": "رييل كمبودي", "name_en": "Cambodian Riel", "symbol_ar": "៛", "symbol_en": "៛"},
    "TWD": {"name_ar": "دولار تايواني جديد", "name_en": "New Taiwan Dollar", "symbol_ar": "NT$", "symbol_en": "NT$"},
    "MVR": {"name_ar": "روفية مالديفية", "name_en": "Maldivian Rufiyaa", "symbol_ar": "Rf", "symbol_en": "Rf"},
    "KZT": {"name_ar": "تينغي كازاخستاني", "name_en": "Kazakhstani Tenge", "symbol_ar": "₸", "symbol_en": "₸"},
    "UZS": {"name_ar": "سوم أوزبكستاني", "name_en": "Uzbekistani Som", "symbol_ar": "so'm", "symbol_en": "so'm"},
    "AFN": {"name_ar": "أفغاني أفغانستاني", "name_en": "Afghan Afghani", "symbol_ar": "؋", "symbol_en": "؋"},
    "BND": {"name_ar": "دولار بروني", "name_en": "Brunei Dollar", "symbol_ar": "B$", "symbol_en": "B$"},
    "FJD": {"name_ar": "دولار فيجي", "name_en": "Fijian Dollar", "symbol_ar": "FJ$", "symbol_en": "FJ$"},
    "MNT": {"name_ar": "توغروغ منغولي", "name_en": "Mongolian Tugrik", "symbol_ar": "₮", "symbol_en": "₮"},

    # الأمريكتين
    "MXN": {"name_ar": "بيزو مكسيكي", "name_en": "Mexican Peso", "symbol_ar": "Mex$", "symbol_en": "Mex$"},
    "ARS": {"name_ar": "بيزو أرجنتيني", "name_en": "Argentine Peso", "symbol_ar": "$", "symbol_en": "$"},
    "CLP": {"name_ar": "بيزو تشيلي", "name_en": "Chilean Peso", "symbol_ar": "$", "symbol_en": "$"},
    "COP": {"name_ar": "بيزو كولومبي", "name_en": "Colombian Peso", "symbol_ar": "$", "symbol_en": "$"},
    "PEN": {"name_ar": "سول بيروفي", "name_en": "Peruvian Sol", "symbol_ar": "S/", "symbol_en": "S/"},
    "UYU": {"name_ar": "بيزو أوروغواي", "name_en": "Uruguayan Peso", "symbol_ar": "$", "symbol_en": "$"},
    "CRC": {"name_ar": "كولون كوستاريكي", "name_en": "Costa Rican Colon", "symbol_ar": "₡", "symbol_en": "₡"},
    "DOP": {"name_ar": "بيزو دومينيكاني", "name_en": "Dominican Peso", "symbol_ar": "RD$", "symbol_en": "RD$"},
    "GTQ": {"name_ar": "كيتزال غواتيمالي", "name_en": "Guatemalan Quetzal", "symbol_ar": "Q", "symbol_en": "Q"},
    "HNL": {"name_ar": "لمبيرة هندوراسية", "name_en": "Honduran Lempira", "symbol_ar": "L", "symbol_en": "L"},
    "PAB": {"name_ar": "بالبوا بنمي", "name_en": "Panamanian Balboa", "symbol_ar": "B/.", "symbol_en": "B/."},
    "PYG": {"name_ar": "غواراني باراغواي", "name_en": "Paraguayan Guarani", "symbol_ar": "₲", "symbol_en": "₲"},
    "BOB": {"name_ar": "بوليفيانو بوليفي", "name_en": "Bolivian Boliviano", "symbol_ar": "Bs", "symbol_en": "Bs"},
    "JMD": {"name_ar": "دولار جامايكي", "name_en": "Jamaican Dollar", "symbol_ar": "J$", "symbol_en": "J$"},
    "TTD": {"name_ar": "دولار ترينيداد", "name_en": "Trinidad Dollar", "symbol_ar": "TT$", "symbol_en": "TT$"},

    # أفريقيا
    "NGN": {"name_ar": "نايرا نيجيرية", "name_en": "Nigerian Naira", "symbol_ar": "₦", "symbol_en": "₦"},
    "KES": {"name_ar": "شلن كيني", "name_en": "Kenyan Shilling", "symbol_ar": "KSh", "symbol_en": "KSh"},
    "GHS": {"name_ar": "سيدي غاني", "name_en": "Ghanaian Cedi", "symbol_ar": "GH₵", "symbol_en": "GH₵"},
    "TZS": {"name_ar": "شلن تنزاني", "name_en": "Tanzanian Shilling", "symbol_ar": "TSh", "symbol_en": "TSh"},
    "UGX": {"name_ar": "شلن أوغندي", "name_en": "Ugandan Shilling", "symbol_ar": "USh", "symbol_en": "USh"},
    "ETB": {"name_ar": "بير إثيوبي", "name_en": "Ethiopian Birr", "symbol_ar": "Br", "symbol_en": "Br"},
    "ZMW": {"name_ar": "كواشا زامبية", "name_en": "Zambian Kwacha", "symbol_ar": "ZK", "symbol_en": "ZK"},
    "NAD": {"name_ar": "دولار ناميبي", "name_en": "Namibian Dollar", "symbol_ar": "N$", "symbol_en": "N$"},
    "BWP": {"name_ar": "بولا بوتسوانية", "name_en": "Botswana Pula", "symbol_ar": "P", "symbol_en": "P"},
    "MZN": {"name_ar": "متكال موزمبيقي", "name_en": "Mozambican Metical", "symbol_ar": "MT", "symbol_en": "MT"},
    "AOA": {"name_ar": "كوانزا أنغولية", "name_en": "Angolan Kwanza", "symbol_ar": "Kz", "symbol_en": "Kz"},
    "RWF": {"name_ar": "فرنك رواندي", "name_en": "Rwandan Franc", "symbol_ar": "FRw", "symbol_en": "FRw"},
    "MUR": {"name_ar": "روبية موريشية", "name_en": "Mauritian Rupee", "symbol_ar": "Rs", "symbol_en": "Rs"},
    "XOF": {"name_ar": "فرنك غرب أفريقي", "name_en": "West African CFA", "symbol_ar": "CFA", "symbol_en": "CFA"},
    "XAF": {"name_ar": "فرنك وسط أفريقي", "name_en": "Central African CFA", "symbol_ar": "FCFA", "symbol_en": "FCFA"},
}

def get_currency_choices() -> List[Tuple[str, str]]:
    """قائمة خيارات العملة لحقول نماذج Django."""
    choices = []
    for code, info in CURRENCIES_DATA.items():
        label = f"{info['name_ar']} ({code} - {info['symbol_ar']})"
        choices.append((code, label))
    return choices


def get_currency_info(code: str) -> Dict[str, str]:
    """جلب معلومات عملة محددة مع قيم افتراضية آمنة."""
    code_upper = str(code or "").strip().upper()
    if code_upper in CURRENCIES_DATA:
        return CURRENCIES_DATA[code_upper]
    # Default fallback
    return {
        "name_ar": "ريال",
        "name_en": "Riyal",
        "symbol_ar": "ر.س",
        "symbol_en": "SAR",
    }


def format_currency_amount(amount: Any, code: str = "SAR", lang: str = "ar") -> str:
    """تنسيق المبلغ مع العملة والرمز المناسب للغة."""
    info = get_currency_info(code)
    try:
        val = float(amount)
        val_str = f"{val:,.2f}" if (val % 1 != 0) else f"{int(val)}"
    except Exception:
        val_str = str(amount)

    if lang == "ar":
        return f"{val_str} {info['symbol_ar']}"
    return f"{val_str} {info['symbol_en']}"
