import httpx
import logging
from app.schemas.screening import GreenbankPaymentInput, ScreeningDecisionResponse
from app.services.mapping import map_to_mulisa_payload
from app.core.config import settings  
logger = logging.getLogger(__name__)

IDEMPOTENCY_CACHE = {}

class ScreeningService:
    def __init__(self):
        self.mulisa_url = settings.MULISA_API_URL
        self.policy = settings.UNAVAILABLE_POLICY
        
        if self.policy not in ["FAIL_OPEN", "FAIL_CLOSED"]:
            raise ValueError("CRITICAL: UNAVAILABLE_POLICY must be configured as 'FAIL_OPEN' or 'FAIL_CLOSED' at startup.")

    async def screen_payment(self, payment: GreenbankPaymentInput) -> ScreeningDecisionResponse:
        if payment.reference in IDEMPOTENCY_CACHE:
            logger.info(f"Duplicate transaction found for ref: {payment.reference}. Returning stored result.")
            return IDEMPOTENCY_CACHE[payment.reference]

        mulisa_payload = map_to_mulisa_payload(payment)
        decision = "unavailable"
        policy_applied = None

        async with httpx.AsyncClient() as client:
            for attempt in range(2): 
                try:
                    response = await client.post(
                        f"{self.mulisa_url}/screen",
                        json=mulisa_payload,
                        timeout=2.0 
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        decision = data.get("decision")  
                        break
                    elif response.status_code in [500, 502, 503, 504]:
                        logger.warning(f"Mulisa returned retryable status {response.status_code}. Attempt {attempt + 1}")
                        continue  
                    else:
                        break  
                        
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    logger.warning(f"Connection timeout/error on attempt {attempt + 1}: {str(e)}")
                    if attempt == 1:  
                        break

        if decision == "unavailable":
            policy_applied = self.policy
            decision = "cleared" if self.policy == "FAIL_OPEN" else "flagged"
            logger.error(f"Mulisa down. Applied fail-safe policy: {self.policy} -> Marked as {decision}")

        result = ScreeningDecisionResponse(
            reference=payment.reference,
            decision=decision.lower(),
            policy_applied=policy_applied
        )

        IDEMPOTENCY_CACHE[payment.reference] = result
        return result
