"""Optional, persistent credit guard for a limited free-credit import."""
from decimal import Decimal, InvalidOperation
import json
import re


class BudgetStop(RuntimeError):
    pass


class ImportBudget:
    def __init__(self, path):
        self.path = path

    @property
    def enabled(self):
        return self.path.exists()

    def video_ids(self, ready_count):
        """Optional ordered snapshot limits the batch to specific channel uploads."""
        try:
            config = json.loads(self.path.read_text())
            if config.get('stopped'):
                return []
            target = config.get('target_ready_videos')
            if target is not None:
                if type(target) is not int or target < 1:
                    raise ValueError('Invalid target')
                if ready_count >= target:
                    raise BudgetStop(f'Import complete: {target} videos indexed. Importing is paused.')
            ids = config.get('video_ids')
            if ids is not None and (not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or
                    any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', v) for v in ids) or len(set(ids)) != len(ids)):
                raise ValueError('Invalid video snapshot')
            return ids
        except BudgetStop:
            raise
        except (OSError, ValueError, TypeError, AttributeError):
            raise BudgetStop('Limited import paused because its video selection could not be verified.') from None

    def authorize(self, client, content):
        """Check current credits before every upload; never change provider billing.

        UTF-8 byte count is a conservative text-token allowance, plus an operation
        buffer. This is a local forecast guard, not the provider's invoice/spend cap.
        Callers serialize uploads so asynchronous documents cannot build up a bill.
        """
        try:
            config = json.loads(self.path.read_text())
            floor = Decimal(str(config['minimum_balance_usd']))
            maximum = config['max_new_documents']
            submitted = config.get('submitted', 0)
            if (not floor.is_finite() or floor < 0 or type(maximum) is not int or
                    maximum < 1 or type(submitted) is not int or submitted < 0):
                raise ValueError('Invalid budget')
            if config.get('stopped'):
                raise BudgetStop(config.get('stop_reason', 'Limited import is paused.'))
            if submitted >= maximum:
                raise BudgetStop('Limited import reached its document limit. Review remaining credits before continuing.')
            billing = client.request('GET', '/v3/auth/billing')
            if billing.get('resetDate') != config.get('reset_date'):
                raise BudgetStop('Limited import paused at a billing-period change. Review credits before continuing.')
            payment = client.request('GET', '/v3/auth/billing/auto-topups')
            if billing.get('plan') != 'free' or payment.get('hasPaymentMethod') is not False or payment.get('autoTopup') is not None:
                raise BudgetStop('Limited import paused because free-plan billing settings changed.')
            credits = billing['credits']
            if credits.get('label') != 'USD':
                raise ValueError('Unknown credit unit')
            balance = Decimal(str(credits['balance']))
            if not balance.is_finite() or balance < 0:
                raise ValueError('Invalid credit balance')
            allowance = Decimal(len(content.encode('utf-8'))) / Decimal(1_000_000) + Decimal('0.01')
            if balance - allowance < floor:
                raise BudgetStop(f'Limited import paused to preserve ${floor:.2f} in credits; the next video may exceed the remaining budget.')
            config.update(submitted=submitted + 1, last_balance_usd=str(balance), last_allowance_usd=str(allowance))
            self._save(config)  # Reserve a submission slot before the remote mutation.
        except BudgetStop:
            raise
        except (OSError, ValueError, TypeError, KeyError, InvalidOperation, RuntimeError):
            raise BudgetStop('Limited import paused because its budget or billing balance could not be verified.') from None

    def stop(self, reason):
        try:
            config = json.loads(self.path.read_text())
        except (OSError, ValueError):
            config = {}
        config.update(stopped=True, stop_reason=reason)
        self._save(config)

    def _save(self, config):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(config, indent=2) + '\n')
        temporary.replace(self.path)
