# Python 3.14 compatibility patch for Django BaseContext.__copy__
# In Python 3.14, copy.copy(super()) returns the super proxy object instead of copying the underlying object,
# which causes AttributeError: 'super' object has no attribute 'dicts' during template context copying.
try:
    from django.template import context as _django_context

    def _base_context_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    _django_context.BaseContext.__copy__ = _base_context_copy
except Exception:
    pass
