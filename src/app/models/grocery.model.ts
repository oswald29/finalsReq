export interface GroceryItem {
  id: number;
  name: string;
  quantity: number;
  budget: number;
  purchased: boolean;
  createdAt?: string;
  purchasedAt?: string | null;
}

export type GroceryPayload = Omit<GroceryItem, 'id' | 'createdAt' | 'purchasedAt'>;
export type GroceryPatch = Partial<GroceryPayload>;

export function groceryLineTotal(item: Pick<GroceryItem, 'quantity' | 'budget'>): number {
  return (Math.round(item.budget * 100) * item.quantity) / 100;
}
