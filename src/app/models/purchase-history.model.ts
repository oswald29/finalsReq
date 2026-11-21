export interface PurchasedHistoryItem {
  id: number;
  productName: string;
  category: string;
  quantity: number;
  unitPrice: number;
  expense: number;
  purchasedAt: string;
}
