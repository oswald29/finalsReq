import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { environment } from '../../environments/environment';

import { GroceryService } from './grocery.service';

describe('GroceryService', () => {
  let service: GroceryService;
  let httpTestingController: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [GroceryService, provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(GroceryService);
    httpTestingController = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTestingController.verify();
  });

  it('multiplies each unit price by quantity in the planned total', () => {
    service.loadItems().subscribe();
    httpTestingController.expectOne(`${environment.apiBaseUrl}/groceries`).flush([
      { id: 1, name: 'Rice', quantity: 2, budget: 180, purchased: false },
      { id: 2, name: 'Eggs', quantity: 12, budget: 10, purchased: true },
    ]);

    expect(service.plannedBudget()).toBe(360);
  });

  it('patches a grocery item and updates the local state', () => {
    service.patchItem(1, { purchased: true }).subscribe();
    const request = httpTestingController.expectOne(`${environment.apiBaseUrl}/groceries/1`);

    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({ purchased: true });
    request.flush({ id: 1, name: 'Rice', quantity: 2, budget: 180, purchased: true });

    expect(service.items()).toEqual([{ id: 1, name: 'Rice', quantity: 2, budget: 180, purchased: true }]);
  });
});
