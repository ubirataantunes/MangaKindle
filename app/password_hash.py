import sys
from getpass import getpass

from argon2 import PasswordHasher

MIN_PASSWORD_LENGTH = 8


def generate_password_hash(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    return PasswordHasher().hash(password)


def main() -> int:
    password = getpass("Senha do app: ")
    confirmation = getpass("Repita a senha: ")

    if password != confirmation:
        print("As senhas não são iguais.", file=sys.stderr)
        return 1

    try:
        print(generate_password_hash(password))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
