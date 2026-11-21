import { HttpErrorResponse } from '@angular/common/http';
import { computed, signal, type Signal, type WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import type { ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Expense } from '../models/expense.model';
import type { GroceryItem, GroceryPayload } from '../models/grocery.model';
import type { PurchasedHistoryItem } from '../models/purchase-history.model';
import { AuthService } from '../services/auth.service';
import { ExpenseService } from '../services/expense.service';
import { GroceryService } from '../services/grocery.service';

import { HomePage } from './home.page';

describe('HomePage', () => {
  let component: HomePage;
  let fixture: ComponentFixture<HomePage>;
  let expenseService: {
    expenses: WritableSignal<Expense[]>;
    isLoading: WritableSignal<boolean>;
    error: WritableSignal<string | null>;
    loadExpenses: ReturnType<typeof vi.fn>;
    createExpense: ReturnType<typeof vi.fn>;
    updateExpense: ReturnType<typeof vi.fn>;
    deleteExpense: ReturnType<typeof vi.fn>;
    clear: ReturnType<typeof vi.fn>;
  };
  let authService: {
    token: WritableSignal<string | null>;
    user: WritableSignal<{ id: number; email: string; name: string; monthlyBudget: number } | null>;
    logout: ReturnType<typeof vi.fn>;
    loadCurrentUser: ReturnType<typeof vi.fn>;
    updateMonthlyBudget: ReturnType<typeof vi.fn>;
  };
  let groceryService: {
    items: WritableSignal<GroceryItem[]>;
    purchasedHistory: WritableSignal<PurchasedHistoryItem[]>;
    plannedBudget: Signal<number>;
    isLoading: WritableSignal<boolean>;
    error: WritableSignal<string | null>;
    loadItems: ReturnType<typeof vi.fn>;
    loadPurchasedHistory: ReturnType<typeof vi.fn>;
    createItem: ReturnType<typeof vi.fn>;
    updateItem: ReturnType<typeof vi.fn>;
    patchItem: ReturnType<typeof vi.fn>;
    deleteItem: ReturnType<typeof vi.fn>;
    deletePurchasedHistoryItem: ReturnType<typeof vi.fn>;
    clear: ReturnType<typeof vi.fn>;
  };

  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(async () => {
    expenseService = {
      expenses: signal<Expense[]>([]),
      isLoading: signal(false),
      error: signal<string | null>(null),
      loadExpenses: vi.fn(() => of([])),
      createExpense: vi.fn(() => of({ id: 1, title: '', amount: 0, category: '', date: '', notes: '' })),
      updateExpense: vi.fn(() => of({ id: 1, title: '', amount: 0, category: '', date: '', notes: '' })),
      deleteExpense: vi.fn(() => of(void 0)),
      clear: vi.fn(),
    };
    authService = {
      token: signal<string | null>(null),
      user: signal<{ id: number; email: string; name: string; monthlyBudget: number } | null>({
        id: 1,
        email: 'user@example.com',
        name: 'Test User',
        monthlyBudget: 25000,
      }),
      logout: vi.fn(() => of(void 0)),
      loadCurrentUser: vi.fn(() => of({ id: 1, email: 'user@example.com', name: 'Test User', monthlyBudget: 25000 })),
      updateMonthlyBudget: vi.fn((monthlyBudget: number) => {
        const updatedUser = {
          ...(authService.user() ?? { id: 1, email: 'user@example.com', name: 'Test User', monthlyBudget: 25000 }),
          monthlyBudget,
        };
        authService.user.set(updatedUser);
        return of(updatedUser);
      }),
    };
    groceryService = {
      items: signal<GroceryItem[]>([]),
      purchasedHistory: signal<PurchasedHistoryItem[]>([]),
      plannedBudget: computed(() =>
        groceryService
          .items()
          .filter((item) => !item.purchased)
          .reduce((total, item) => total + item.budget * item.quantity, 0),
      ),
      isLoading: signal(false),
      error: signal<string | null>(null),
      loadItems: vi.fn(() => of([])),
      loadPurchasedHistory: vi.fn(() => of([])),
      createItem: vi.fn((item: GroceryPayload) => of({ id: 1, ...item })),
      updateItem: vi.fn((id: number, item: GroceryPayload) => of({ id, ...item })),
      patchItem: vi.fn((id: number, changes: Partial<GroceryPayload>) =>
        of({
          id,
          name: 'Eggs',
          quantity: 12,
          budget: 120,
          purchased: false,
          ...changes,
        }),
      ),
      deleteItem: vi.fn(() => of(void 0)),
      deletePurchasedHistoryItem: vi.fn(() => of(void 0)),
      clear: vi.fn(),
    };

    await TestBed.configureTestingModule({
      imports: [HomePage],
      providers: [
        { provide: ExpenseService, useValue: expenseService },
        { provide: AuthService, useValue: authService },
        { provide: GroceryService, useValue: groceryService },
        provideRouter([]),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(HomePage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('loads expenses when the page initializes', () => {
    expect(expenseService.loadExpenses).toHaveBeenCalledOnce();
    expect(groceryService.loadItems).toHaveBeenCalledOnce();
    expect(groceryService.loadPurchasedHistory).toHaveBeenCalledOnce();
  });

  it('creates a grocery item with its quantity and budget', () => {
    component.groceryName.set('Rice');
    component.groceryQuantity.set('2');
    component.groceryItemBudget.set('180');

    const event = { preventDefault: vi.fn() } as unknown as SubmitEvent;
    component.addGrocery(event);

    expect(groceryService.createItem).toHaveBeenCalledWith({
      name: 'Rice',
      quantity: 2,
      budget: 180,
      purchased: false,
    });
    expect(component.groceryName()).toBe('');
  });

  it('patches grocery purchased status through the service', () => {
    const item: GroceryItem = {
      id: 7,
      name: 'Eggs',
      quantity: 12,
      budget: 120,
      purchased: false,
    };

    component.setGroceryPurchased(item, true);

    expect(groceryService.patchItem).toHaveBeenCalledWith(7, { purchased: true });
    expect(groceryService.loadPurchasedHistory).toHaveBeenCalledTimes(2);
  });

  it('filters purchased history by category', () => {
    groceryService.purchasedHistory.set([
      {
        id: 1,
        productName: 'Rice',
        category: 'Groceries',
        quantity: 2,
        unitPrice: 180,
        expense: 360,
        purchasedAt: '2026-11-07 12:00:00',
      },
      {
        id: 2,
        productName: 'Milk',
        category: 'Groceries',
        quantity: 1,
        unitPrice: 90,
        expense: 90,
        purchasedAt: '2026-11-06 12:00:00',
      },
    ]);

    component.setCategoryFilter('Groceries');

    expect(component.filteredPurchasedHistory().map((item) => item.productName)).toEqual(['Rice', 'Milk']);
    component.setCategoryFilter('Food');
    expect(component.filteredPurchasedHistory()).toEqual([]);
  });

  it('displays the extended grocery price for the selected quantity', () => {
    const item: GroceryItem = {
      id: 8,
      name: 'Rice',
      quantity: 2,
      budget: 180,
      purchased: false,
    };

    expect(component.groceryLineTotal(item)).toBe(360);
  });

  it('shows the unit price, quantity, and multiplied price in the grocery list', () => {
    groceryService.items.set([{ id: 8, name: 'Rice', quantity: 2, budget: 180, purchased: false }]);
    const groceryDetails = fixture.nativeElement.querySelector('details') as HTMLDetailsElement;
    groceryDetails.open = true;
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('each × 2');
    expect(component.groceryLineTotal(groceryService.items()[0])).toBe(360);
  });

  it('shows only unpurchased grocery totals as the grocery budget remaining', () => {
    groceryService.items.set([
      { id: 8, name: 'Rice', quantity: 2, budget: 180, purchased: false },
      { id: 9, name: 'Eggs', quantity: 12, budget: 10, purchased: true },
    ]);

    expect(component.groceryBudget()).toBe(360);
  });

  it('does not deduct planned groceries from the monthly budget until they are purchased', () => {
    groceryService.items.set([
      { id: 8, name: 'Rice', quantity: 2, budget: 180, purchased: false },
      { id: 9, name: 'Eggs', quantity: 12, budget: 10, purchased: true },
    ]);

    expect(component.groceryBudget()).toBe(360);
    expect(component.budgetRemaining()).toBe(25000);
    expect(component.budgetProgress()).toBe(0);
  });

  it('defaults the monthly budget to zero when no user budget is loaded', () => {
    authService.user.set(null);

    expect(component.monthlyBudget()).toBe(0);
    expect(component.budgetRemaining()).toBe(0);
  });

  it('deducts this month purchased groceries from the monthly remaining budget', () => {
    const now = new Date();
    const purchasedAt = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01 12:00:00`;
    groceryService.items.set([{ id: 8, name: 'Rice', quantity: 2, budget: 180, purchased: true }]);
    groceryService.purchasedHistory.set([
      {
        id: 1,
        productName: 'Rice',
        category: 'Groceries',
        quantity: 2,
        unitPrice: 180,
        expense: 360,
        purchasedAt,
      },
    ]);

    expect(component.monthlySpent()).toBe(360);
    expect(component.budgetRemaining()).toBe(25000 - 360);
  });

  it('shows the cumulative amount over budget as purchases and bills are added', () => {
    const date = new Date().toISOString();
    expenseService.expenses.set([{ id: 1, title: 'Budget limit', amount: 25000, category: 'Other', date, notes: '' }]);
    fixture.detectChanges();

    expect(component.isBudgetExceeded()).toBe(false);
    expect(fixture.nativeElement.textContent).not.toContain('Budget exceeded');

    groceryService.purchasedHistory.set([
      {
        id: 1,
        productName: 'Groceries',
        category: 'Groceries',
        quantity: 1,
        unitPrice: 75,
        expense: 75,
        purchasedAt: date,
      },
    ]);
    fixture.detectChanges();

    let warning = fixture.nativeElement.querySelector('.budget-exceeded-message') as HTMLElement | null;
    expect(component.isBudgetExceeded()).toBe(true);
    expect(component.budgetOverspent()).toBe(75);
    expect(warning?.textContent).toContain('75.00');

    expenseService.expenses.set([
      { id: 1, title: 'Budget limit', amount: 25000, category: 'Other', date, notes: '' },
      { id: 2, title: 'Electricity bill', amount: 250, category: 'Bills & Utilities', date, notes: '' },
    ]);
    fixture.detectChanges();

    warning = fixture.nativeElement.querySelector('.budget-exceeded-message') as HTMLElement | null;
    expect(component.budgetOverspent()).toBe(325);
    expect(component.budgetRemaining()).toBe(0);
    expect(warning?.textContent).toContain('325.00');
    expect(warning?.classList.contains('budget-exceeded-message')).toBe(true);
  });

  it('saves the monthly budget through the account service', () => {
    component.setMonthlyBudget('18000');
    const event = { preventDefault: vi.fn() } as unknown as SubmitEvent;

    component.saveMonthlyBudget(event);

    expect(authService.updateMonthlyBudget).toHaveBeenCalledWith(18000);
    expect(component.profileSaved()).toBe(true);
    expect(component.monthlyBudget()).toBe(18000);
  });

  it('shows a dashboard category breakdown derived from saved expenses', () => {
    expenseService.expenses.set([
      { id: 1, title: 'Lunch', amount: 100, category: 'Food', date: new Date().toISOString(), notes: '' },
      { id: 2, title: 'Bus', amount: 50, category: 'Transport', date: new Date().toISOString(), notes: '' },
    ]);

    expect(component.monthlySpent()).toBe(150);
    expect(component.categoryBreakdown()).toEqual([
      { category: 'Food', amount: 100, percent: (100 / 150) * 100 },
      { category: 'Transport', amount: 50, percent: (50 / 150) * 100 },
    ]);
  });

  it('creates an expense using the form values', () => {
    component.title.set('Lunch');
    component.amount.set('150');
    component.category.set('Food');
    component.date.set('2026-11-07');
    component.notes.set('Meal');

    const event = { preventDefault: vi.fn() } as unknown as SubmitEvent;
    component.saveExpense(event);

    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(expenseService.createExpense).toHaveBeenCalledWith({
      title: 'Lunch',
      amount: 150,
      category: 'Food',
      date: '2026-11-07',
      notes: 'Meal',
    });
  });

  it('updates the chosen expense details in the form', () => {
    const expense: Expense = {
      id: 'expense-1',
      title: 'Bus',
      amount: 30,
      category: 'Transport',
      date: '2026-11-07T00:00:00.000Z',
      notes: 'To school',
    };

    component.editExpense(expense);

    expect(component.editingId()).toBe(expense.id);
    expect(component.title()).toBe(expense.title);
    expect(component.amount()).toBe('30');
    expect(component.date()).toBe('2026-11-07');
  });

  it('updates an expense when the edit form is submitted', () => {
    component.editExpense({
      id: 'expense-1',
      title: 'Bus',
      amount: 30,
      category: 'Transport',
      date: '2026-11-07',
      notes: '',
    });

    const event = { preventDefault: vi.fn() } as unknown as SubmitEvent;
    component.saveExpense(event);

    expect(expenseService.updateExpense).toHaveBeenCalledWith('expense-1', {
      title: 'Bus',
      amount: 30,
      category: 'Transport',
      date: '2026-11-07',
      notes: '',
    });
  });

  it('deletes an expense after native confirmation and shows a toast', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.deleteExpense('expense-1');

    expect(window.confirm).toHaveBeenCalledWith('Delete this expense?');
    expect(expenseService.deleteExpense).toHaveBeenCalledWith('expense-1');
    expect(component.deleteToast()).toBe('Expense deleted.');
  });

  it('does not delete an expense when native confirmation is canceled', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    component.deleteExpense('expense-1');

    expect(expenseService.deleteExpense).not.toHaveBeenCalled();
    expect(component.deleteToast()).toBeNull();
  });

  it('deletes a grocery item after native confirmation and shows a toast', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    component.deleteGrocery(7);

    expect(window.confirm).toHaveBeenCalledWith('Remove this item?');
    expect(groceryService.deleteItem).toHaveBeenCalledWith(7);
    expect(component.deleteToast()).toBe('Item deleted.');
  });

  it('deletes selected history items after native confirmation and shows a toast', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    groceryService.purchasedHistory.set([
      {
        id: 1,
        productName: 'Rice',
        category: 'Groceries',
        quantity: 2,
        unitPrice: 180,
        expense: 360,
        purchasedAt: '2026-11-07 12:00:00',
      },
      {
        id: 2,
        productName: 'Milk',
        category: 'Groceries',
        quantity: 1,
        unitPrice: 90,
        expense: 90,
        purchasedAt: '2026-11-06 12:00:00',
      },
    ]);
    component.selectedPurchasedIds.set([1, 2]);

    component.deleteSelectedPurchased();

    expect(window.confirm).toHaveBeenCalledWith('Delete 2 selected history items?');
    expect(groceryService.deletePurchasedHistoryItem).toHaveBeenCalledTimes(2);
    expect(component.selectedPurchasedIds()).toEqual([]);
    expect(component.deleteToast()).toBe('2 history items deleted.');
  });

  it('clears stale history selections without asking for confirmation', () => {
    vi.spyOn(window, 'confirm');
    component.selectedPurchasedIds.set([1]);

    component.deleteSelectedPurchased();

    expect(window.confirm).not.toHaveBeenCalled();
    expect(groceryService.deletePurchasedHistoryItem).not.toHaveBeenCalled();
    expect(component.selectedPurchasedIds()).toEqual([]);
    expect(component.selectedPurchasedCount()).toBe(0);
  });

  it('does not delete history items when native confirmation is canceled', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    groceryService.purchasedHistory.set([
      {
        id: 1,
        productName: 'Rice',
        category: 'Groceries',
        quantity: 2,
        unitPrice: 180,
        expense: 360,
        purchasedAt: '2026-11-07 12:00:00',
      },
      {
        id: 2,
        productName: 'Milk',
        category: 'Groceries',
        quantity: 1,
        unitPrice: 90,
        expense: 90,
        purchasedAt: '2026-11-06 12:00:00',
      },
    ]);
    component.selectedPurchasedIds.set([1, 2]);

    component.deleteSelectedPurchased();

    expect(groceryService.deletePurchasedHistoryItem).not.toHaveBeenCalled();
    expect(component.selectedPurchasedIds()).toEqual([1, 2]);
    expect(component.deleteToast()).toBeNull();
  });

  it('filters expenses by category', () => {
    expenseService.expenses.set([
      { id: 1, title: 'Lunch', amount: 100, category: 'Food', date: '2026-11-07', notes: '' },
      { id: 2, title: 'Bus', amount: 30, category: 'Transport', date: '2026-11-07', notes: '' },
      { id: 3, title: 'Dinner', amount: 200, category: 'Food', date: '2026-11-06', notes: '' },
    ]);
    component.setCategoryFilter('Food');
    component.setCategoryFilter('Food');

    expect(component.filteredExpenses().map((expense) => expense.title)).toEqual(['Lunch', 'Dinner']);
  });

  it('clears the category filter when opening History', () => {
    expenseService.expenses.set([
      { id: 1, title: 'Water bill', amount: 3000, category: 'Bills & Utilities', date: '2026-11-20', notes: '' },
    ]);
    component.setCategoryFilter('Food');

    component.selectTab('history');

    expect(component.selectedCategory()).toBe('all');
    expect(component.filteredExpenses().map((expense) => expense.title)).toEqual(['Water bill']);
  });

  it('clears the category filter from the no-matching-transactions message', () => {
    expenseService.expenses.set([
      { id: 1, title: 'Water bill', amount: 3000, category: 'Bills & Utilities', date: '2026-11-20', notes: '' },
    ]);
    component.selectTab('history');
    component.setCategoryFilter('Food');
    fixture.detectChanges();

    const nativeElement = fixture.nativeElement as HTMLElement;
    const clearButton = Array.from(nativeElement.querySelectorAll('button')).find(
      (button) => button.textContent?.trim() === 'Clear category filter',
    );
    expect(clearButton).toBeDefined();
    clearButton?.click();
    fixture.detectChanges();

    expect(component.filteredExpenses().map((expense) => expense.title)).toEqual(['Water bill']);
    expect(fixture.nativeElement.textContent).toContain('Water bill');
  });

  it('shows purchased history below the category filters without the database label', () => {
    expenseService.expenses.set([
      { id: 1, title: 'Water bill', amount: 3000, category: 'Bills & Utilities', date: '2026-11-20', notes: '' },
    ]);
    component.selectTab('history');
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).not.toContain('SAVED TO DATABASE');
    expect(text.indexOf('All categories')).toBeLessThan(text.indexOf('Purchased history'));
    expect(text.indexOf('Purchased history')).toBeLessThan(text.indexOf('Water bill'));
  });

  it('shows an error when loading expenses fails', () => {
    expenseService.loadExpenses.mockReturnValue(throwError(() => new Error('network error')));

    component.loadExpenses();

    expect(component.pageError()).toContain('Could not load expenses');
  });

  it('shows the API message when the expense request is unauthorized', () => {
    expenseService.loadExpenses.mockReturnValue(
      throwError(() => new HttpErrorResponse({ status: 401, error: { error: 'Sign in to continue.' } })),
    );

    component.loadExpenses();

    expect(component.pageError()).toBe('Sign in to continue.');
  });
});
