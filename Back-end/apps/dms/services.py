from django.db.models import Q

from .models import Conversation


def ordered_pair(a_id, b_id):
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def get_conversation(user_id, other_id, create=False):
    a, b = ordered_pair(user_id, other_id)
    if create:
        convo, _ = Conversation.objects.get_or_create(user_a_id=a, user_b_id=b)
        return convo
    return Conversation.objects.filter(user_a_id=a, user_b_id=b).first()


def conversations_for(user_id):
    return Conversation.objects.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id))
