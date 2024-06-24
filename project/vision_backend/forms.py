from django import forms


class BackendMainForm(forms.Form):
    confidence_threshold = forms.IntegerField(
        min_value=0, max_value=100)
    label_mode = forms.ChoiceField(
        choices=(('full', 'Labels'), ('func', 'Functional Groups')),
        initial='full')


class CmTestForm(forms.Form):
    nlabels = forms.IntegerField(min_value=0, max_value=200)    
    namelength = forms.IntegerField(min_value=10, max_value=100)
