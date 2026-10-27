from django import template
from django.utils import translation
from django.utils.safestring import mark_safe
from core.i18n_catalog import get_translation, I18N_CATALOG

register = template.Library()


@register.filter(name="t", is_safe=True)
def t_filter(value, lang=None):
    if value is None:
        return ""
    text = str(value)
    if not text.strip():
        return value
    active_lang = lang or translation.get_language() or "ar"
    if "-" in active_lang:
        active_lang = active_lang.split("-")[0]
    if active_lang == "ar":
        return value
    res = get_translation(text, active_lang, default=None)
    if res is not None:
        return mark_safe(res) if hasattr(value, "__html__") else res
    stripped = text.strip()
    res = get_translation(stripped, active_lang, default=None)
    if res is not None:
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        final_str = f"{leading}{res}{trailing}"
        return mark_safe(final_str) if hasattr(value, "__html__") else final_str
    return value


@register.filter(name="trans5", is_safe=True)
def trans5_filter(value, lang=None):
    return t_filter(value, lang)


@register.simple_tag(takes_context=True)
def trans_text(context, text, lang=None):
    target_lang = lang or context.get("CURRENT_LANG") or translation.get_language() or "ar"
    return t_filter(text, target_lang)
