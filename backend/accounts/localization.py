from django.conf import settings


def product_email_language(user):
    # Turkish copy remains a development draft until bilingual human review.
    return "tr" if (settings.DEBUG and getattr(user, "is_active", False)
                    and getattr(user, "product_language", None) == "tr") else "en"
