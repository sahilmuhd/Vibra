from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Profile

User = get_user_model()


def signup_payload(**overrides):
    data = {
        "name": "Test Person", "username": "tester", "email": "tester@example.com",
        "password": "S0me-Strong-Pass!", "dob": "2000-01-01",
    }
    data.update(overrides)
    return data


class SignupTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_signup_creates_user_profile_and_returns_tokens_and_id(self):
        res = self.client.post("/api/auth/signup/", signup_payload(), format="json")
        self.assertEqual(res.status_code, 201, res.content)
        user = User.objects.get(username="tester")
        self.assertEqual(res.data["user"]["id"], user.id)
        self.assertEqual(res.data["user"]["username"], "tester")
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertTrue(Profile.objects.filter(user=user).exists())

    def test_username_is_normalised_to_lowercase(self):
        res = self.client.post("/api/auth/signup/", signup_payload(username="MixedCase_1"), format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["user"]["username"], "mixedcase_1")

    def test_rejects_invalid_usernames(self):
        for bad in ["ab", "has space", "<img src=x onerror=alert(1)>", "emoji😀name", "a" * 31, "dash-name"]:
            res = self.client.post("/api/auth/signup/", signup_payload(username=bad, email=f"{abs(hash(bad))}@e.com"), format="json")
            self.assertEqual(res.status_code, 400, f"{bad!r} should be rejected: {res.content}")
            self.assertIn("username", res.data)

    def test_rejects_duplicate_username_case_insensitively(self):
        self.client.post("/api/auth/signup/", signup_payload(), format="json")
        res = self.client.post("/api/auth/signup/", signup_payload(username="TESTER", email="other@example.com"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("username", res.data)

    def test_rejects_duplicate_email_case_insensitively(self):
        self.client.post("/api/auth/signup/", signup_payload(), format="json")
        res = self.client.post("/api/auth/signup/", signup_payload(username="other", email="TESTER@example.com"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("email", res.data)

    def test_rejects_under_13_and_future_dob(self):
        too_young = (date.today() - timedelta(days=365 * 10)).isoformat()
        future = (date.today() + timedelta(days=5)).isoformat()
        for dob in (too_young, future):
            res = self.client.post("/api/auth/signup/", signup_payload(dob=dob), format="json")
            self.assertEqual(res.status_code, 400, dob)
            self.assertIn("dob", res.data)

    def test_rejects_weak_password(self):
        res = self.client.post("/api/auth/signup/", signup_payload(password="12345678"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("password", res.data)


class LoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.post("/api/auth/signup/", signup_payload(), format="json")

    def test_login_with_username(self):
        res = self.client.post("/api/auth/login/", {"username": "tester", "password": "S0me-Strong-Pass!"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("access", res.data)

    def test_login_is_case_insensitive_on_username(self):
        res = self.client.post("/api/auth/login/", {"username": "  TeStEr ", "password": "S0me-Strong-Pass!"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)

    def test_login_with_email(self):
        res = self.client.post("/api/auth/login/", {"username": "Tester@Example.com", "password": "S0me-Strong-Pass!"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)

    def test_wrong_password_is_401(self):
        res = self.client.post("/api/auth/login/", {"username": "tester", "password": "nope-nope-nope"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_refresh_returns_new_access_token(self):
        login = self.client.post("/api/auth/login/", {"username": "tester", "password": "S0me-Strong-Pass!"}, format="json")
        res = self.client.post("/api/auth/login/refresh/", {"refresh": login.data["refresh"]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)


class MeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        res = self.client.post("/api/auth/signup/", signup_payload(), format="json")
        self.user = User.objects.get(username="tester")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")

    def test_me_requires_auth(self):
        self.assertEqual(APIClient().get("/api/auth/me/").status_code, 401)

    def test_me_returns_id_and_counts(self):
        res = self.client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["id"], self.user.id)
        self.assertEqual(res.data["followers_count"], 0)
        self.assertEqual(res.data["following_count"], 0)

    def test_patch_updates_bio_but_not_username_or_level(self):
        res = self.client.patch("/api/auth/me/", {"bio": "hello", "username": "hacker", "level": 99}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "hello")
        self.assertEqual(profile.username, "tester")
        self.assertEqual(profile.level, 1)
        self.assertEqual(self.user.username, "tester")

    def test_superuser_without_profile_gets_one_instead_of_500(self):
        admin = User.objects.create_superuser("rootuser", "root@example.com", "S0me-Strong-Pass!")
        self.assertFalse(Profile.objects.filter(user=admin).exists())
        client = APIClient()
        client.force_authenticate(admin)
        res = client.get("/api/auth/me/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(Profile.objects.filter(user=admin).exists())


class GuestTests(TestCase):
    def test_guest_login_returns_tokens_and_guest_profile(self):
        res = APIClient().post("/api/auth/guest/")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn("access", res.data)
        self.assertTrue(Profile.objects.get(user_id=res.data["user"]["id"]).is_guest)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.post("/api/auth/signup/", signup_payload(), format="json")
        self.user = User.objects.get(username="tester")
        cache.clear()

    def test_request_is_identical_for_known_and_unknown_email(self):
        known = self.client.post("/api/auth/password-reset/", {"email": "tester@example.com"}, format="json")
        unknown = self.client.post("/api/auth/password-reset/", {"email": "nobody@example.com"}, format="json")
        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)  # only the real account got mail

    def test_confirm_sets_new_password_and_token_is_single_use(self):
        cache.set("pw_reset_tok123", self.user.pk, 60)
        res = self.client.post("/api/auth/password-reset/confirm/", {"token": "tok123", "new_password": "An0ther-Strong-Pass!"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("An0ther-Strong-Pass!"))
        again = self.client.post("/api/auth/password-reset/confirm/", {"token": "tok123", "new_password": "Yet-An0ther-Pass!"}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_confirm_rejects_weak_password_and_keeps_token_valid(self):
        cache.set("pw_reset_tok456", self.user.pk, 60)
        res = self.client.post("/api/auth/password-reset/confirm/", {"token": "tok456", "new_password": "12345678"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIsNotNone(cache.get("pw_reset_tok456"))

    def test_confirm_rejects_unknown_token(self):
        res = self.client.post("/api/auth/password-reset/confirm/", {"token": "bogus", "new_password": "An0ther-Strong-Pass!"}, format="json")
        self.assertEqual(res.status_code, 400)
