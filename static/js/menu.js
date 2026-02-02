// Debug: log when menu.js loads
console.log('menu.js loaded, menuApp function defined');

function menuApp() {
    console.log('menuApp() called');
    return {
        categories: categoriesData || [],
        products: productsData || [],
        selectedCategory: null,
        searchQuery: '',
        cart: [],
        showCart: false,
        orderSuccess: false,
        orderNumber: '',
        tableNumber: null,

        // Theme
        theme: localStorage.getItem('theme') || 'light',

        // Feedback properties
        showFeedback: false,
        feedbackRating: 0,
        feedbackPhone: '',
        feedbackComment: '',
        feedbackSubmitting: false,
        feedbackSuccess: false,

        // Promo code properties
        promoCode: '',
        promoApplied: false,
        promoMessage: '',
        promoError: false,
        discountAmount: 0,
        discountType: '',
        discountValue: 0,

        init() {
            // Watch theme changes
            this.$watch('theme', val => {
                localStorage.setItem('theme', val);
                document.documentElement.setAttribute('data-theme', val);
            });

            // Check for table parameter from QR code
            const urlParams = new URLSearchParams(window.location.search);
            const tableNum = urlParams.get('table');
            if (tableNum) {
                this.tableNumber = parseInt(tableNum);
            }

            // Select first category by default
            if (this.categories.length > 0) {
                this.selectedCategory = this.categories[0]._id;
            }

            // Load cart from localStorage
            const savedCart = localStorage.getItem('pos_cart');
            if (savedCart) {
                this.cart = JSON.parse(savedCart);
            }

            // Watch cart changes
            this.$watch('cart', () => {
                localStorage.setItem('pos_cart', JSON.stringify(this.cart));
            });
        },

        get filteredProducts() {
            let result = this.products;

            // Search filter
            if (this.searchQuery.trim()) {
                const query = this.searchQuery.toLowerCase().trim();
                result = result.filter(p =>
                    p.name.toLowerCase().includes(query) ||
                    (p.description && p.description.toLowerCase().includes(query))
                );
                // Skip category filter when searching
                return result;
            }

            // Category filter
            if (this.selectedCategory) {
                result = result.filter(p => p.category_id === this.selectedCategory);
            }

            return result;
        },

        getCategoryName(catId) {
            const cat = this.categories.find(c => c._id === catId);
            return cat ? cat.name : '';
        },

        getCategoryIcon(iconName) {
            const icons = {
                'star': '<svg viewBox="0 0 24 24"><path d="M12,17.27L18.18,21L16.54,13.97L22,9.24L14.81,8.62L12,2L9.19,8.62L2,9.24L7.45,13.97L5.82,21L12,17.27Z"/></svg>',
                'coffee': '<svg viewBox="0 0 24 24"><path d="M2,21V19H20V21H2M20,8V5H18V8H20M20,3A2,2 0 0,1 22,5V8A2,2 0 0,1 20,10H18V13A4,4 0 0,1 14,17H8A4,4 0 0,1 4,13V3H20M16,5H6V13A2,2 0 0,0 8,15H14A2,2 0 0,0 16,13V5Z"/></svg>',
                'cup': '<svg viewBox="0 0 24 24"><path d="M18.32,8H5.67L5.23,4H18.77M3,2L5,20.23C5.13,21.23 5.97,22 7,22H17C18,22 18.87,21.23 19,20.23L21,2H3Z"/></svg>',
                'sun': '<svg viewBox="0 0 24 24"><path d="M12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,2L14.39,5.42C13.65,5.15 12.84,5 12,5C11.16,5 10.35,5.15 9.61,5.42L12,2M3.34,7L7.5,6.65C6.9,7.16 6.36,7.78 5.94,8.5C5.5,9.24 5.25,10 5.11,10.79L3.34,7M3.36,17L5.12,13.23C5.26,14 5.53,14.78 5.95,15.5C6.37,16.24 6.91,16.86 7.5,17.37L3.36,17M20.65,7L18.88,10.79C18.74,10 18.47,9.23 18.05,8.5C17.63,7.78 17.1,7.15 16.5,6.64L20.65,7M20.64,17L16.5,17.36C17.09,16.85 17.62,16.22 18.04,15.5C18.46,14.77 18.73,14 18.87,13.21L20.64,17M12,22L9.59,18.56C10.33,18.83 11.14,19 12,19C12.82,19 13.63,18.83 14.37,18.56L12,22Z"/></svg>',
                'sandwich': '<svg viewBox="0 0 24 24"><path d="M22,15H2C2,16.66 3.34,18 5,18H19C20.66,18 22,16.66 22,15M22,12H2V13H22V12M5,7L2,12H22L19,7H5M13,9V10H11V9H13M7,9H9V10H7V9M15,10V9H17V10H15Z"/></svg>',
                'leaf': '<svg viewBox="0 0 24 24"><path d="M17,8C8,10 5.9,16.17 3.82,21.34L5.71,22L6.66,19.7C7.14,19.87 7.64,20 8,20C19,20 22,3 22,3C21,5 14,5.25 9,6.25C4,7.25 2,11.5 2,13.5C2,15.5 3.75,17.25 3.75,17.25C7,8 17,8 17,8Z"/></svg>',
                'bowl': '<svg viewBox="0 0 24 24"><path d="M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4M9,8A2,2 0 0,0 7,10A2,2 0 0,0 9,12A2,2 0 0,0 11,10A2,2 0 0,0 9,8M15,8A2,2 0 0,0 13,10A2,2 0 0,0 15,12A2,2 0 0,0 17,10A2,2 0 0,0 15,8M12,14A4,4 0 0,0 8,18H16A4,4 0 0,0 12,14Z"/></svg>',
                'burger': '<svg viewBox="0 0 24 24"><path d="M22,16H2C2,16.91 2.37,17.72 2.97,18.31C3.56,18.89 4.38,19.25 5.29,19.25H18.71C19.62,19.25 20.44,18.89 21.03,18.31C21.63,17.72 22,16.91 22,16M2,14H22C22,13.08 21.63,12.26 21.03,11.67C20.44,11.09 19.62,10.75 18.71,10.75H5.29C4.38,10.75 3.56,11.09 2.97,11.67C2.37,12.26 2,13.08 2,14M22,9C22,7.62 21.17,6.43 20,5.87V5C20,4.45 19.55,4 19,4H5C4.45,4 4,4.45 4,5V5.87C2.83,6.43 2,7.62 2,9H22Z"/></svg>',
                'pizza': '<svg viewBox="0 0 24 24"><path d="M12,15A2,2 0 0,1 10,13C10,11.89 10.9,11 12,11A2,2 0 0,1 14,13A2,2 0 0,1 12,15M7,7C7,5.89 7.89,5 9,5A2,2 0 0,1 11,7A2,2 0 0,1 9,9C7.89,9 7,8.1 7,7M12,2C8.43,2 5.23,3.54 3,6L12,22L21,6C18.78,3.54 15.57,2 12,2Z"/></svg>',
                'cake': '<svg viewBox="0 0 24 24"><path d="M12,6C13.11,6 14,5.1 14,4C14,3.62 13.9,3.27 13.71,2.97L12,0L10.29,2.97C10.1,3.27 10,3.62 10,4A2,2 0 0,0 12,6M16.6,16L15.53,14.92L14.45,16C13.15,17.29 10.87,17.3 9.56,16L8.5,14.92L7.4,16C6.75,16.64 5.88,17 4.96,17C4.23,17 3.56,16.77 3,16.39V21A1,1 0 0,0 4,22H20A1,1 0 0,0 21,21V16.39C20.44,16.77 19.77,17 19.04,17C18.12,17 17.25,16.64 16.6,16M18,9H13V7H11V9H6A3,3 0 0,0 3,12V13.54C3,14.62 3.88,15.5 4.96,15.5C5.5,15.5 6,15.3 6.34,14.93L8.5,12.8L10.61,14.93C11.35,15.67 12.64,15.67 13.38,14.93L15.5,12.8L17.65,14.93C18,15.3 18.5,15.5 19.03,15.5C20.11,15.5 21,14.62 21,13.54V12A3,3 0 0,0 18,9Z"/></svg>',
                'tag': '<svg viewBox="0 0 24 24"><path d="M5.5,7A1.5,1.5 0 0,1 4,5.5A1.5,1.5 0 0,1 5.5,4A1.5,1.5 0 0,1 7,5.5A1.5,1.5 0 0,1 5.5,7M21.41,11.58L12.41,2.58C12.05,2.22 11.55,2 11,2H4C2.89,2 2,2.89 2,4V11C2,11.55 2.22,12.05 2.59,12.41L11.58,21.41C11.95,21.77 12.45,22 13,22C13.55,22 14.05,21.77 14.41,21.41L21.41,14.41C21.78,14.05 22,13.55 22,13C22,12.44 21.77,11.94 21.41,11.58Z"/></svg>'
            };
            return icons[iconName] || icons['tag'];
        },

        addToCart(product) {
            const isCombo = product.item_type === 'combo';
            const itemId = isCombo ? `combo_${product._id}` : product._id;
            const existingIndex = this.cart.findIndex(item => item.product_id === itemId);
            if (existingIndex >= 0) {
                this.cart[existingIndex].qty++;
            } else {
                this.cart.push({
                    product_id: itemId,
                    name: product.name,
                    price: isCombo ? product.combo_price : product.price,
                    qty: 1,
                    is_combo: isCombo,
                    combo_items: isCombo ? product.items : null
                });
            }
        },

        removeFromCart(index) {
            this.cart.splice(index, 1);
        },

        increaseQty(index) {
            this.cart[index].qty++;
        },

        decreaseQty(index) {
            if (this.cart[index].qty > 1) {
                this.cart[index].qty--;
            } else {
                this.removeFromCart(index);
            }
        },

        getSubtotal() {
            return this.cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
        },

        getTotal() {
            const subtotal = this.getSubtotal();
            return subtotal - this.discountAmount;
        },

        async applyPromoCode() {
            if (!this.promoCode.trim()) return;

            try {
                const subtotal = this.getSubtotal();
                const response = await fetch(`/api/promo-codes/validate?code=${encodeURIComponent(this.promoCode)}&order_total=${subtotal}`, {
                    method: 'POST'
                });

                const result = await response.json();

                if (result.valid) {
                    this.promoApplied = true;
                    this.discountAmount = result.discount_amount;
                    this.discountType = result.discount_type;
                    this.discountValue = result.discount_value;
                    this.promoMessage = `Знижка ${result.discount_type === 'percentage' ? result.discount_value + '%' : result.discount_value + ' грн'} застосована!`;
                    this.promoError = false;
                } else {
                    this.promoError = true;
                    this.promoMessage = result.error || 'Невірний промокод';
                }
            } catch (error) {
                console.error('Promo code error:', error);
                this.promoError = true;
                this.promoMessage = 'Помилка перевірки промокоду';
            }
        },

        removePromoCode() {
            this.promoCode = '';
            this.promoApplied = false;
            this.promoMessage = '';
            this.promoError = false;
            this.discountAmount = 0;
            this.discountType = '';
            this.discountValue = 0;
        },

        async checkout() {
            if (this.cart.length === 0) return;

            try {
                const orderData = {
                    items: this.cart,
                    order_type: 'dine_in'
                };
                if (this.tableNumber) {
                    orderData.table_number = this.tableNumber;
                }
                if (this.promoApplied && this.promoCode) {
                    orderData.promo_code = this.promoCode;
                }

                const response = await fetch('/api/orders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(orderData)
                });

                if (response.ok) {
                    const order = await response.json();
                    this.orderNumber = order.order_number;
                    this.cart = [];
                    this.showCart = false;
                    this.orderSuccess = true;
                    // Reset promo code
                    this.removePromoCode();
                } else {
                    alert('Помилка при створенні замовлення');
                }
            } catch (error) {
                console.error('Checkout error:', error);
                alert('Помилка при створенні замовлення');
            }
        },

        async submitFeedback() {
            if (this.feedbackRating === 0) return;

            this.feedbackSubmitting = true;

            try {
                const response = await fetch('/api/feedbacks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        rating: this.feedbackRating,
                        phone: this.feedbackPhone,
                        comment: this.feedbackComment
                    })
                });

                if (response.ok) {
                    this.feedbackRating = 0;
                    this.feedbackPhone = '';
                    this.feedbackComment = '';
                    this.showFeedback = false;
                    this.feedbackSuccess = true;
                } else {
                    alert('Помилка при надсиланні відгуку');
                }
            } catch (error) {
                console.error('Feedback error:', error);
                alert('Помилка при надсиланні відгуку');
            } finally {
                this.feedbackSubmitting = false;
            }
        }
    };
}
