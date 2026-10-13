import re

from django import forms

STRENGTH_CHOICES = [
    (1, "Everything, including weak signals"),
    (2, "Moderate and strong signals"),
    (3, "Strong signals only"),
]


class PreferencesForm(forms.Form):
    watchlist = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "NABIL, NICA, UPPER"}),
        help_text="Stock symbols separated by commas or spaces. Leave empty to hear about every stock.",
    )
    min_strength = forms.TypedChoiceField(choices=STRENGTH_CHOICES, coerce=int, label="Which signals to send")
    include_intraday = forms.BooleanField(required=False, label="Also send the midday updates (11:15 and 14:15), not only the market close")
    is_active = forms.BooleanField(required=False, label="Send me digests")

    def __init__(self, *args, known_symbols=frozenset(), **kwargs):
        super().__init__(*args, **kwargs)
        self.known_symbols = known_symbols

    def clean_watchlist(self):
        symbols = {s.upper() for s in re.split(r"[\s,;]+", self.cleaned_data["watchlist"]) if s}
        unknown = sorted(symbols - self.known_symbols) if self.known_symbols else []
        if unknown:
            raise forms.ValidationError(f"Not a listed stock: {', '.join(unknown)}")
        if len(", ".join(symbols)) > 1000:
            raise forms.ValidationError("That watchlist is too long.")
        return symbols
