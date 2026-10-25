"""Rate limits that fit carrier-grade NAT (docs/DEPLOY.md "Rate limits").

Pharmacy staff are on mobile networks where hundreds of people share one public address, and a
whole shift opens the mini app in the same minute. So a limit about a person counts per person,
once the view knows who it is (the Telegram signature or the session token checked out), and the
limit per address is only a generous ceiling against floods:

    class SignIn(APIView):
        throttle_classes = (AddressRateThrottle,)
        address_throttle_scope = "telegram_auth_address"    # every request, before anything

        def post(self, request):
            person = verify(request)                        # the signature checks out
            throttle_person(self, request, "telegram_auth", person.id)

Rates live in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] by scope (THROTTLE_RATES in the
environment overrides them). The client address is DRF's: the last X-Forwarded-For hop behind
NUM_PROXIES proxies (Caddy).
"""

from rest_framework.throttling import SimpleRateThrottle


class AddressRateThrottle(SimpleRateThrottle):
    """A ceiling per client address, at the rate named by the view's `address_throttle_scope`.

    A fixed window counted with one atomic increment, so hundreds of requests from one address
    in the same second neither queue on nor overwrite each other's count (DRF's own throttles
    rewrite a list of timestamps per address on every request)."""

    def __init__(self):
        # The scope is the view's, so the rate is read in allow_request.
        pass

    def allow_request(self, request, view):
        self.scope = getattr(view, "address_throttle_scope", None)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        self.now = self.timer()
        window = int(self.now // self.duration)
        self.window_ends = (window + 1) * self.duration
        key = f"{self.get_cache_key(request, view)}_{window}"
        if self.cache.add(key, 1, self.duration + 1):
            return True
        try:
            count = self.cache.incr(key)
        except ValueError:  # it expired in between: this request starts the window again
            self.cache.set(key, 1, self.duration + 1)
            return True
        return count <= self.num_requests

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}

    def wait(self):
        return max(self.window_ends - self.timer(), 1)


class PersonRateThrottle(SimpleRateThrottle):
    """The rate of `scope` for one verified person, account or session (`ident`)."""

    def __init__(self, scope: str, ident):
        self.scope = scope
        self.ident = str(ident)
        super().__init__()

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.ident}


def throttle_person(view, request, scope: str, ident) -> None:
    """Answer 429 (with Retry-After) once `ident` has used up the rate of `scope`."""
    throttle = PersonRateThrottle(scope, ident)
    if not throttle.allow_request(request, view):
        view.throttled(request, throttle.wait())
