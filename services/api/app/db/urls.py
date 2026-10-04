"""One PostgreSQL URL contract, with verified cloud TLS and safe errors."""

from sqlalchemy.engine import URL, make_url


def postgres_url(
    value: str, *, production: bool = False, setting: str = "DATABASE_URL"
) -> URL:
    try:
        url = make_url(value)
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError()
        url = url.set(drivername="postgresql+psycopg")
        if not url.host or not url.database:
            raise ValueError()
        # libpq query parameters must not override the inspected endpoint.
        if set(url.query) & {
            "host",
            "hostaddr",
            "port",
            "dbname",
            "user",
            "password",
            "service",
            "servicefile",
        }:
            raise ValueError()
        if production and (
            not url.host.endswith(".neon.tech")
            or not url.username
            or not url.password
            or url.query.get("sslmode") != "verify-full"
            or url.query.get("sslrootcert") != "system"
        ):
            raise ValueError()
        return url
    except Exception:
        raise ValueError(
            f"{setting} must be a PostgreSQL URL"
            + (
                " with a Neon host, credentials, sslmode=verify-full "
                "and sslrootcert=system"
                if production
                else ""
            )
        ) from None
