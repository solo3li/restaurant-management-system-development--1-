from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        try:
            import core.signals  # noqa
        except Exception:
            pass

        # Python 3.14 compatibility patch for Django BaseContext.__copy__
        try:
            from django.template import context as django_context

            def _base_context_copy(self):
                duplicate = self.__class__.__new__(self.__class__)
                duplicate.__dict__.update(self.__dict__)
                duplicate.dicts = self.dicts[:]
                return duplicate

            django_context.BaseContext.__copy__ = _base_context_copy
        except Exception:
            pass
