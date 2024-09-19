import hashlib

from django.contrib.auth.hashers import (
    BasePasswordHasher, PBKDF2PasswordHasher)


class PBKDF2WrappedSHA1PasswordHasher(PBKDF2PasswordHasher):
    """
    From:
    https://docs.djangoproject.com/en/1.10/topics/auth/passwords/#password-upgrading-without-requiring-a-login
    """
    algorithm = 'pbkdf2_wrapped_sha1'

    def encode_sha1_hash(self, sha1_hash, salt, iterations=None):
        return super().encode(sha1_hash, salt, iterations)

    def encode(self, password, salt, iterations=None):
        _, _, sha1_hash = \
            SHA1PasswordHasher().encode(password, salt).split('$', 2)
        return self.encode_sha1_hash(sha1_hash, salt, iterations)


class SHA1PasswordHasher(BasePasswordHasher):
    """
    From older versions of Django. This is used by the wrapped password
    hasher. This shouldn't be used directly (unwrapped) because the algorithm
    is not secure enough.
    """
    algorithm = 'sha1'

    def encode(self, password, salt):
        self._check_encode_args(password, salt)
        hash = hashlib.sha1((salt + password).encode()).hexdigest()
        return '%s$%s$%s' % (self.algorithm, salt, hash)
