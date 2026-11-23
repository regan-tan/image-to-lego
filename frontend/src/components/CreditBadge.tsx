import { Link } from "react-router-dom";

import { useCredits } from "../hooks/useCredits";

interface CreditBadgeProps {
  accessToken: string;
  userId: string;
}

export function CreditBadge({ accessToken, userId }: CreditBadgeProps) {
  const credits = useCredits(accessToken, userId);
  if (credits.isPending) return <span className="credit-badge credit-badge--pending" role="status">Loading credits</span>;
  if (credits.isError) return <Link className="credit-badge credit-badge--error" to="/profile" aria-label="Credits unavailable; view profile">Credits unavailable</Link>;
  const balance = credits.data.balance;
  return <Link className="credit-badge" to="/profile" aria-label={`${balance} credits remaining`}><svg aria-hidden="true" viewBox="0 0 24 24"><path d="m12 2.5 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5-5.8-3.1-5.8 3.1 1.1-6.5-4.7-4.6 6.5-.9z" /></svg><span>{balance}</span></Link>;
}
