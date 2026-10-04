"""Synthetic Document Desk service adapter.

This is the only component allowed to cause an effect, and the gateway calls it exactly once per
permitted invocation. It performs no network calls: documents, comments and deletions live in the
durable repository, which makes the side-effect counter independently verifiable in SQL.

The adapter receives the *sanitized* projection of the request. Raw text never reaches it.
"""
from dataclasses import dataclass, field

OUTCOME_SUCCEEDED = 'succeeded'
OUTCOME_FAILED = 'failed'
OUTCOME_SKIPPED = 'not_started'


@dataclass
class DispatchResult:
    outcome: str
    output_text: str | None = None
    reason: str | None = None
    detail: dict = field(default_factory=dict)


class DocumentDeskAdapter:
    service_id = 'document-desk'

    def __init__(self, repository):
        self.repository = repository

    def dispatch(self, action_id: str, *, document_id: str, text: str | None,
                 invocation_id: str, principal_id: str) -> DispatchResult:
        if action_id == 'documents.read':
            document = self.repository.read_document(document_id)
            if document is None:
                self._record(invocation_id, action_id, OUTCOME_FAILED, 0, {'reason': 'not_found'})
                return DispatchResult(OUTCOME_FAILED, None, 'document_not_found')
            self._record(invocation_id, action_id, OUTCOME_SUCCEEDED, len(document['body']),
                         {'classification': document['classification']})
            return DispatchResult(OUTCOME_SUCCEEDED, document['body'], None,
                                  {'classification': document['classification'],
                                   'documentId': document_id})

        if action_id == 'documents.comment':
            comment = self.repository.add_comment(document_id, text or '', principal_id, invocation_id)
            if comment is None:
                self._record(invocation_id, action_id, OUTCOME_FAILED, 0, {'reason': 'not_found'})
                return DispatchResult(OUTCOME_FAILED, None, 'document_not_found')
            confirmation = 'Comment stored on document %s.' % document_id
            self._record(invocation_id, action_id, OUTCOME_SUCCEEDED, len(confirmation),
                         {'commentId': comment['comment_id']})
            return DispatchResult(OUTCOME_SUCCEEDED, confirmation, None,
                                  {'commentId': comment['comment_id'], 'documentId': document_id})

        if action_id == 'documents.delete':
            deleted = self.repository.delete_document(document_id, invocation_id)
            if not deleted:
                self._record(invocation_id, action_id, OUTCOME_FAILED, 0, {'reason': 'not_found'})
                return DispatchResult(OUTCOME_FAILED, None, 'document_not_found')
            self._record(invocation_id, action_id, OUTCOME_SUCCEEDED, 0, {'documentId': document_id})
            return DispatchResult(OUTCOME_SUCCEEDED, None, None, {'documentId': document_id})

        self._record(invocation_id, action_id, OUTCOME_FAILED, 0, {'reason': 'unsupported_action'})
        return DispatchResult(OUTCOME_FAILED, None, 'unsupported_action')

    def _record(self, invocation_id, action_id, outcome, result_bytes, detail):
        self.repository.record_effect({
            'invocation_id': invocation_id,
            'service_id': self.service_id,
            'action_id': action_id,
            'outcome': outcome,
            'result_bytes': result_bytes,
            'detail': detail,
        })
