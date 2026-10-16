class RoutingError(Exception):
    """Base class for controlled routing failures."""


class NoRouteFound(RoutingError):
    pass


class SnapDistanceExceeded(RoutingError):
    pass


class RoutingExpansionLimitExceeded(RoutingError):
    pass


class GraphUnavailable(RoutingError):
    pass
