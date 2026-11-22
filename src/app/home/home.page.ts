import { CurrencyPipe, DatePipe, DecimalPipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import type { OnDestroy, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import {
  AlertController,
  IonButton,
  IonCheckbox,
  IonContent,
  IonInput,
  IonItem,
  IonSelect,
  IonSelectOption,
  IonTextarea,
} from '@ionic/angular';

import type { Expense, ExpensePayload } from '../models/expense.model';
import { groceryLineTotal } from '../models/grocery.model';
import type { GroceryItem, GroceryPayload } from '../models/grocery.model';
import { AuthService } from '../services/auth.service';
import { ExpenseService } from '../services/expense.service';
import { GroceryService } from '../services/grocery.service';

@Component({
  selector: 'app-home',
  templateUrl: 'home.page.html',
  imports: [
    CurrencyPipe,
    DatePipe,
    DecimalPipe,
    IonButton,
    IonCheckbox,
    IonContent,
    IonInput,
    IonItem,
    IonSelect,
    IonSelectOption,
    IonTextarea,
  ],
})
export class HomePage implements OnInit, OnDestroy {
  private readonly expenseService = inject(ExpenseService);
  private readonly groceryService = inject(GroceryService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly alertController = inject(AlertController);

  readonly categories = [
    'Food & Dining',
    'Transportation',
    'Shopping',
    'Utilities',
    'Entertainment',
    'Health & Medicines',
    'Subscriptions',
    'Other',
    'Food',
    'Transport',
    'Bills',
    'Bills & Utilities',
    'Groceries',
  ];
  readonly quickPayments = [
    { title: 'Water bill', category: 'Bills & Utilities' },
    { title: 'Electricity bill', category: 'Bills & Utilities' },
    { title: 'Internet bill', category: 'Bills & Utilities' },
    { title: 'Mobile load', category: 'Bills & Utilities' },
    { title: 'Health & Medicines', category: 'Health & Medicines' },
    { title: 'Subscriptions', category: 'Subscriptions' },
    { title: 'Transportation', category: 'Transportation' },
  ];
  readonly activeTab = signal<'home' | 'history' | 'profile'>('home');
  readonly showExpenseForm = signal(false);
  readonly user = this.authService.user;
  readonly monthlyBudgetInput = signal('');
  readonly profileError = signal<string | null>(null);
  readonly profileSaved = signal(false);
  readonly darkMode = signal(false);
  readonly expenses = this.expenseService.expenses;
  readonly isLoading = this.expenseService.isLoading;
  readonly serviceError = this.expenseService.error;
  readonly groceries = this.groceryService.items;
  readonly groceryBudget = this.groceryService.plannedBudget;
  readonly groceryIsLoading = this.groceryService.isLoading;
  readonly groceryError = this.groceryService.error;
  readonly purchasedHistory = this.groceryService.purchasedHistory;
  readonly purchaseHistoryError = signal<string | null>(null);
  readonly monthExpenses = computed(() => {
    const now = new Date();
    const month = now.getMonth();
    const year = now.getFullYear();
    return this.expenses().filter((expense) => {
      const date = new Date(expense.date);
      return date.getMonth() === month && date.getFullYear() === year;
    });
  });
  readonly monthlySpent = computed(() => {
    const now = new Date();
    const monthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    const expenseTotal = this.monthExpenses().reduce((total, expense) => total + expense.amount, 0);
    const purchasedGroceryTotal = this.purchasedHistory()
      .filter((purchase) => purchase.purchasedAt.slice(0, 7) === monthKey)
      .reduce((total, purchase) => total + purchase.expense, 0);
    return expenseTotal + purchasedGroceryTotal;
  });
  readonly monthlyBudget = computed(() => this.user()?.monthlyBudget ?? 0);
  readonly budgetCommitted = computed(() => this.monthlySpent());
  readonly isBudgetExceeded = computed(() => this.budgetCommitted() > this.monthlyBudget());
  readonly budgetOverspent = computed(() => Math.max(0, this.budgetCommitted() - this.monthlyBudget()));
  readonly budgetRemaining = computed(() => Math.max(0, this.monthlyBudget() - this.budgetCommitted()));
  readonly budgetProgress = computed(() =>
    Math.min(100, (this.budgetCommitted() / Math.max(1, this.monthlyBudget())) * 100),
  );
  readonly recentExpenses = computed(() =>
    [...this.expenses()]
      .sort((left, right) => new Date(right.date).getTime() - new Date(left.date).getTime())
      .slice(0, 4),
  );
  readonly filteredPurchasedHistory = computed(() => {
    const categoryFilter = this.selectedCategory();
    return categoryFilter === 'all' || categoryFilter === 'Groceries' ? this.purchasedHistory() : [];
  });
  readonly categoryBreakdown = computed(() => {
    const totals = new Map<string, number>();
    for (const expense of this.monthExpenses()) {
      totals.set(expense.category, (totals.get(expense.category) ?? 0) + expense.amount);
    }
    return [...totals.entries()]
      .map(([category, amount]) => ({
        category,
        amount,
        percent: this.monthlySpent() ? (amount / this.monthlySpent()) * 100 : 0,
      }))
      .sort((left, right) => right.amount - left.amount);
  });

  readonly title = signal('');
  readonly amount = signal('');
  readonly category = signal('');
  readonly date = signal(new Date().toISOString().slice(0, 10));
  readonly notes = signal('');
  readonly selectedCategory = signal('all');
  readonly editingId = signal<Expense['id'] | null>(null);
  readonly pageError = signal<string | null>(null);
  readonly deleteToast = signal<string | null>(null);
  readonly groceryName = signal('');
  readonly groceryQuantity = signal('1');
  readonly groceryItemBudget = signal('0');
  readonly groceryPageError = signal<string | null>(null);
  readonly selectedPurchasedIds = signal<number[]>([]);
  readonly selectedPurchasedCount = computed(() => {
    const historyIds = new Set(this.purchasedHistory().map((item) => item.id));
    return this.selectedPurchasedIds().filter((id) => historyIds.has(id)).length;
  });
  private deleteToastTimer: ReturnType<typeof setTimeout> | null = null;
  readonly canAddGrocery = computed(
    () =>
      this.groceryName().trim().length > 0 &&
      Number.isInteger(Number(this.groceryQuantity())) &&
      Number(this.groceryQuantity()) > 0 &&
      Number.isFinite(Number(this.groceryItemBudget())) &&
      Number(this.groceryItemBudget()) >= 0,
  );
  readonly canSave = computed(
    () =>
      this.title().trim().length > 0 &&
      Number.isFinite(Number(this.amount())) &&
      Number(this.amount()) > 0 &&
      this.category().length > 0 &&
      this.date().length > 0,
  );

  readonly filteredExpenses = computed(() => {
    const categoryFilter = this.selectedCategory();
    return this.expenses().filter((expense) => categoryFilter === 'all' || expense.category === categoryFilter);
  });

  ngOnInit(): void {
    const savedTheme = localStorage.getItem('expense_tracker_theme');
    this.darkMode.set(savedTheme === 'dark');
    this.applyDarkMode(this.darkMode());
    this.expenseService.clear();
    this.groceryService.clear();
    this.loadExpenses();
    this.loadGroceries();
    this.loadPurchasedHistory();
    const currentUser = this.authService.user();
    if (currentUser) {
      this.monthlyBudgetInput.set(String(currentUser.monthlyBudget));
    }
    if (this.authService.token()) {
      this.authService.loadCurrentUser().subscribe({
        next: (user) => this.monthlyBudgetInput.set(String(user.monthlyBudget)),
        error: () => this.profileError.set('Could not load your profile. Please sign in again if this continues.'),
      });
    }
  }

  ngOnDestroy(): void {
    if (this.deleteToastTimer !== null) {
      clearTimeout(this.deleteToastTimer);
    }
  }

  loadExpenses(): void {
    this.pageError.set(null);
    this.expenseService.loadExpenses().subscribe({
      error: (error: unknown) =>
        this.pageError.set(this.requestError(error, 'Could not load expenses. Check your connection and try again.')),
    });
  }

  loadGroceries(): void {
    this.groceryPageError.set(null);
    this.groceryService.loadItems().subscribe({
      error: (error: unknown) =>
        this.groceryPageError.set(this.requestError(error, 'Could not load your grocery list. Please try again.')),
    });
  }

  loadPurchasedHistory(): void {
    this.purchaseHistoryError.set(null);
    this.groceryService.loadPurchasedHistory().subscribe({
      next: (history) => {
        const historyIds = new Set(history.map((item) => item.id));
        this.selectedPurchasedIds.update((ids) => ids.filter((id) => historyIds.has(id)));
      },
      error: (error: unknown) =>
        this.purchaseHistoryError.set(this.requestError(error, 'Could not load purchased history. Please try again.')),
    });
  }

  togglePurchasedSelection(id: number, selected: boolean): void {
    this.selectedPurchasedIds.update((ids) =>
      selected ? (ids.includes(id) ? ids : [...ids, id]) : ids.filter((selectedId) => selectedId !== id),
    );
  }

  async deleteSelectedPurchased(): Promise<void> {
    const historyIds = new Set(this.purchasedHistory().map((item) => item.id));
    const ids = this.selectedPurchasedIds().filter((id) => historyIds.has(id));
    if (ids.length === 0) {
      this.selectedPurchasedIds.set([]);
      return;
    }
    const confirmed = await this.confirmDelete(
      `Delete ${ids.length} selected history ${ids.length === 1 ? 'item' : 'items'}?`,
    );
    if (!confirmed) {
      return;
    }

    this.purchaseHistoryError.set(null);
    let remaining = ids.length;
    let failed = false;
    let deletedCount = 0;
    const failedIds: number[] = [];
    for (const id of ids) {
      this.groceryService.deletePurchasedHistoryItem(id).subscribe({
        next: () => {
          deletedCount += 1;
          remaining -= 1;
          if (remaining === 0) {
            this.selectedPurchasedIds.set(failed ? failedIds : []);
            if (failed) this.purchaseHistoryError.set('Some selected items could not be deleted. Please try again.');
            if (deletedCount > 0) {
              this.showDeleteToast(`${deletedCount} history ${deletedCount === 1 ? 'item' : 'items'} deleted.`);
            }
          }
        },
        error: (error: unknown) => {
          failed = true;
          failedIds.push(id);
          remaining -= 1;
          if (remaining === 0) {
            this.purchaseHistoryError.set(
              this.requestError(error, 'Could not delete selected purchased items. Please try again.'),
            );
            this.selectedPurchasedIds.set([...failedIds]);
            if (deletedCount > 0) {
              this.showDeleteToast(`${deletedCount} history ${deletedCount === 1 ? 'item' : 'items'} deleted.`);
            }
          }
        },
      });
    }
  }

  addGrocery(event: SubmitEvent): void {
    event.preventDefault();
    if (!this.canAddGrocery()) {
      this.groceryPageError.set('Enter an item name, a valid quantity, and a non-negative budget.');
      return;
    }

    this.groceryPageError.set(null);
    const item: GroceryPayload = {
      name: this.groceryName().trim(),
      quantity: Number(this.groceryQuantity()),
      budget: Number(this.groceryItemBudget()),
      purchased: false,
    };
    this.groceryService.createItem(item).subscribe({
      next: () => {
        this.groceryName.set('');
        this.groceryQuantity.set('1');
        this.groceryItemBudget.set('0');
      },
      error: (error: unknown) =>
        this.groceryPageError.set(this.requestError(error, 'Could not save this grocery item. Please try again.')),
    });
  }

  setGroceryName(value: string | number | null | undefined): void {
    this.groceryName.set(String(value ?? ''));
  }

  setGroceryQuantity(value: string | number | null | undefined): void {
    this.groceryQuantity.set(String(value ?? ''));
  }

  setGroceryBudget(value: string | number | null | undefined): void {
    this.groceryItemBudget.set(String(value ?? ''));
  }

  groceryLineTotal(item: GroceryItem): number {
    return groceryLineTotal(item);
  }

  setGroceryPurchased(item: GroceryItem, purchased: boolean): void {
    this.groceryService.patchItem(item.id, { purchased }).subscribe({
      next: () => {
        this.loadPurchasedHistory();
      },
      error: (error: unknown) =>
        this.groceryPageError.set(this.requestError(error, `Could not update ${item.name}. Please try again.`)),
    });
  }

  async deleteGrocery(id: number): Promise<void> {
    const confirmed = await this.confirmDelete('Remove this item?');
    if (!confirmed) {
      return;
    }
    this.groceryService.deleteItem(id).subscribe({
      next: () => this.showDeleteToast('Item deleted.'),
      error: (error: unknown) =>
        this.groceryPageError.set(this.requestError(error, 'Could not delete this grocery item. Please try again.')),
    });
  }

  saveExpense(event: SubmitEvent): void {
    event.preventDefault();
    this.pageError.set(null);

    if (!this.canSave()) {
      this.pageError.set('Enter a title, a positive amount, a category, and a date.');
      return;
    }

    const payload: ExpensePayload = {
      title: this.title().trim(),
      amount: Number(this.amount()),
      category: this.category(),
      date: this.date(),
      notes: this.notes().trim(),
    };

    const editingId = this.editingId();
    const request =
      editingId === null
        ? this.expenseService.createExpense(payload)
        : this.expenseService.updateExpense(editingId, payload);

    request.subscribe({
      next: () => {
        this.resetForm();
        this.showExpenseForm.set(false);
        this.activeTab.set('home');
      },
      error: (error: unknown) =>
        this.pageError.set(this.requestError(error, 'Could not save this expense. Please try again.')),
    });
  }

  editExpense(expense: Expense): void {
    this.showExpenseForm.set(true);
    this.editingId.set(expense.id);
    this.title.set(expense.title);
    this.amount.set(String(expense.amount));
    this.category.set(expense.category);
    this.date.set(expense.date.slice(0, 10));
    this.notes.set(expense.notes);
  }

  cancelEdit(): void {
    this.resetForm();
    this.showExpenseForm.set(false);
  }

  openExpenseForm(): void {
    this.resetForm();
    this.showExpenseForm.set(true);
  }

  selectQuickPayment(payment: { title: string; category: string }): void {
    this.title.set(payment.title);
    this.category.set(payment.category);
  }

  closeExpenseForm(): void {
    this.showExpenseForm.set(false);
    this.resetForm();
  }

  saveMonthlyBudget(event: SubmitEvent): void {
    event.preventDefault();
    const budget = Number(this.monthlyBudgetInput());
    if (!Number.isFinite(budget) || budget <= 0) {
      this.profileError.set('Enter a monthly budget greater than zero.');
      return;
    }
    this.profileError.set(null);
    this.profileSaved.set(false);
    this.authService.updateMonthlyBudget(budget).subscribe({
      next: () => this.profileSaved.set(true),
      error: () => this.profileError.set('Could not update your budget. Please try again.'),
    });
  }

  setMonthlyBudget(value: string | number | null | undefined): void {
    this.monthlyBudgetInput.set(String(value ?? ''));
  }

  selectTab(tab: 'home' | 'history' | 'profile'): void {
    this.activeTab.set(tab);
    if (tab === 'history') {
      this.selectedCategory.set('all');
    }
  }

  toggleDarkMode(): void {
    const enabled = !this.darkMode();
    this.darkMode.set(enabled);
    localStorage.setItem('expense_tracker_theme', enabled ? 'dark' : 'light');
    this.applyDarkMode(enabled);
  }

  private applyDarkMode(enabled: boolean): void {
    document.body.classList.toggle('dark', enabled);
  }

  showAllTransactions(): void {
    this.selectTab('history');
  }

  initials(): string {
    return (this.user()?.name ?? 'Expense User')
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('');
  }

  async deleteExpense(id: Expense['id']): Promise<void> {
    const confirmed = await this.confirmDelete('Delete this expense?');
    if (!confirmed) {
      return;
    }

    this.pageError.set(null);
    this.expenseService.deleteExpense(id).subscribe({
      next: () => this.showDeleteToast('Expense deleted.'),
      error: () => this.pageError.set('Could not delete this expense. Please try again.'),
    });
  }

  private async confirmDelete(message: string): Promise<boolean> {
    const alert = await this.alertController.create({
      cssClass: 'delete-confirm-alert',
      message,
      buttons: [
        {
          text: 'Cancel',
          role: 'cancel',
        },
        {
          text: 'Delete',
          role: 'destructive',
          cssClass: 'delete-confirm-button',
        },
      ],
      backdropDismiss: false,
    });
    await alert.present();
    const { role } = await alert.onDidDismiss();
    return role === 'destructive';
  }

  setTitle(value: string | number | null | undefined): void {
    this.title.set(String(value ?? ''));
  }

  setAmount(value: string | number | null | undefined): void {
    this.amount.set(String(value ?? ''));
  }

  setCategory(value: string | undefined): void {
    this.category.set(value ?? '');
  }

  setDate(value: string | null | undefined): void {
    this.date.set(value?.slice(0, 10) ?? '');
  }

  setNotes(value: string | number | null | undefined): void {
    this.notes.set(String(value ?? ''));
  }

  setCategoryFilter(value: string | undefined): void {
    this.selectedCategory.set(value ?? 'all');
  }

  signOut(): void {
    this.expenseService.clear();
    this.groceryService.clear();
    this.authService.logout().subscribe({
      next: () => void this.router.navigateByUrl('/auth'),
      error: () => void this.router.navigateByUrl('/auth'),
    });
  }

  private resetForm(): void {
    this.editingId.set(null);
    this.title.set('');
    this.amount.set('');
    this.category.set('');
    this.date.set(new Date().toISOString().slice(0, 10));
    this.notes.set('');
  }

  private showDeleteToast(message: string): void {
    if (this.deleteToastTimer !== null) {
      clearTimeout(this.deleteToastTimer);
    }
    this.deleteToast.set(message);
    this.deleteToastTimer = setTimeout(() => {
      this.deleteToast.set(null);
      this.deleteToastTimer = null;
    }, 3000);
  }

  private requestError(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse && typeof error.error?.error === 'string') {
      return error.error.error;
    }
    return fallback;
  }
}
