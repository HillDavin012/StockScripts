import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import argparse
import yfinance as yf

# Set seaborn style for better visuals
sns.set(style="whitegrid")

# Function to calculate a single breakeven price for all options of a symbol
def calculate_symbol_breakeven(group):
    total_premium = 0
    total_strike_weight = 0
    for _, row in group.iterrows():
        premium = row['Purchase Price'] * abs(row['Quantity']) * 100  # Per contract
        if row['Quantity'] > 0:  # Long
            total_premium += premium
        else:  # Short
            total_premium -= premium
        total_strike_weight += row['Strike Price'] * abs(row['Quantity'])
    
    avg_strike = total_strike_weight / group['Quantity'].abs().sum() if group['Quantity'].abs().sum() > 0 else 0
    if total_premium > 0:  # Net cost (debit)
        return avg_strike + (total_premium / (group['Quantity'].abs().sum() * 100))
    elif total_premium < 0:  # Net credit
        return avg_strike - (abs(total_premium) / (group['Quantity'].abs().sum() * 100))
    return avg_strike  # Neutral if no net premium

def fetch_current_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.history(period="1d")['Close'].iloc[-1]
        print(f"Fetched current price for {symbol}: {price}")
        return price
    except Exception as e:
        print(f"Failed to fetch price for {symbol} from yfinance: {e}")
        return None

def process_and_visualize(csv_path, output_dir):
    # Validate file path
    if not Path(csv_path).is_file():
        print("File not found. Please check the path and try again.")
        return

    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"Output directory set to: {output_path.resolve()}")

    # Read the CSV with debugging
    try:
        df = pd.read_csv(csv_path, skiprows=2)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Print column names for debugging
    print("Detected column names:", df.columns.tolist())

    # Check if required columns exist
    required_cols = ['Symbol', 'Account']
    for col in required_cols:
        if col not in df.columns:
            print(f"Error: '{col}' column not found in the CSV. Please check the file structure.")
            return

    # Filter to only include options (exclude stocks and cash positions like SPAXX)
    options_df = df[df['Symbol'].str.contains(r'[CP]\d+$', na=False)].copy()

    # Extract underlying symbol (e.g., "NVDA" from "NVDA250417C110")
    options_df['Underlying Symbol'] = options_df['Symbol'].str.extract(r'([A-Za-z]+)')

    # Debug: Print unique Underlying Symbols in options_df
    print("Unique Underlying Symbols in options_df:", options_df['Underlying Symbol'].unique())

    # Ensure numeric columns are properly typed
    numeric_cols = ['Strike Price', 'Purchase Price', 'Quantity']
    for col in numeric_cols:
        if col in options_df.columns:
            options_df[col] = pd.to_numeric(options_df[col], errors='coerce')
        else:
            print(f"Warning: Column '{col}' not found in the data.")

    # Fetch current prices for all unique underlying symbols
    stock_prices = {}
    for symbol in options_df['Underlying Symbol'].unique():
        price = fetch_current_price(symbol)
        if price is not None:
            stock_prices[symbol] = price

    # Debug: Print stock prices found
    print("Stock prices fetched online:", stock_prices)

    # Add Underlying Last to options_df based on fetched prices
    underlying_price_col = 'Underlying Last'
    options_df[underlying_price_col] = options_df['Underlying Symbol'].map(stock_prices)

    # Debug: Print options_df with Underlying Last
    print(f"options_df with {underlying_price_col}:\n{options_df[['Underlying Symbol', underlying_price_col]].dropna()}")

    # Organize by expiration and symbol
    grouped = options_df.groupby(['Expiration', 'Underlying Symbol'])

    # Visualization with lines and spread shading
    for (expiration, symbol), group in grouped:
        # Debug: Print Underlying Last values for this group
        print(f"\nGroup for {symbol} (Expiration: {expiration}):")
        print(f"Underlying price values:\n{group[underlying_price_col].dropna()}")
        if group[underlying_price_col].isna().all():
            print(f"Warning: All {underlying_price_col} values for {symbol} (Expiration: {expiration}) are NaN.")

        # --- FIGURE SIZE AND FONT SETTINGS ---
        plt.figure(figsize=(12, 8))  # Increased height for vertical price axis
        title = f"Options for {symbol} - Expiration: {expiration}"
        plt.title(title, fontsize=16)  # Increased title font size

        # Determine price range for the y-axis
        min_price = min(group['Strike Price'].min(), group[underlying_price_col].min() if not group[underlying_price_col].isna().all() else float('inf')) - 10
        max_price = max(group['Strike Price'].max(), group[underlying_price_col].max() if not group[underlying_price_col].isna().all() else float('-inf')) + 10
        if min_price == float('inf') or max_price == float('-inf'):
            min_price, max_price = 0, 100  # Default range if no valid prices

        # Calculate single breakeven for the symbol
        breakeven = calculate_symbol_breakeven(group)
        if pd.notna(breakeven):
            min_price = min(min_price, breakeven - 10)
            max_price = max(max_price, breakeven + 10)

        # Track used legs to prevent reuse
        used_symbols = set()

        # Check for spreads based on strike order, position, and same account
        if len(group) > 1 and group['Quantity'].min() < 0 and group['Quantity'].max() > 0:
            for option_type in ['C', 'P']:
                long_options = group[(group['Quantity'] > 0) & (group['Call/Put'] == option_type)].sort_values('Strike Price')
                short_options = group[(group['Quantity'] < 0) & (group['Call/Put'] == option_type)].sort_values('Strike Price')
                
                for _, long_row in long_options.iterrows():
                    if long_row['Symbol'] in used_symbols:
                        continue
                    for _, short_row in short_options.iterrows():
                        if short_row['Symbol'] in used_symbols:
                            continue
                        # Check if both legs are in the same account
                        if long_row['Account'] != short_row['Account']:
                            continue
                        
                        low_strike = min(long_row['Strike Price'], short_row['Strike Price'])
                        high_strike = max(long_row['Strike Price'], short_row['Strike Price'])
                        
                        if option_type == 'C':
                            # Call Spreads
                            if long_row['Strike Price'] < short_row['Strike Price']:
                                spread_type = "Debit Call"
                                color = 'green'
                            elif long_row['Strike Price'] > short_row['Strike Price']:
                                spread_type = "Credit Call"
                                color = 'red'
                            else:
                                continue
                        elif option_type == 'P':
                            # Put Spreads
                            if long_row['Strike Price'] > short_row['Strike Price']:
                                spread_type = "Debit Put"
                                color = 'green'
                            elif long_row['Strike Price'] < short_row['Strike Price']:
                                spread_type = "Credit Put"
                                color = 'red'
                            else:
                                continue
                        
                        label = f"{spread_type} Spread: {long_row['Symbol']} & {short_row['Symbol']} (Account: {long_row['Account']})"
                        # Shade horizontally between strikes on y-axis (price)
                        plt.fill_betweenx([low_strike, high_strike], 0, 1, color=color, alpha=0.3, label=label)
                        
                        used_symbols.add(long_row['Symbol'])
                        used_symbols.add(short_row['Symbol'])
                        break

        # Plot horizontal lines for each option strike (x-axis)
        for i, (_, row) in enumerate(group.iterrows()):
            strike = row['Strike Price']
            is_short = row['Quantity'] < 0
            option_type = row['Call/Put']
            label = f"{row['Symbol']} ({'Short' if is_short else 'Long'} {option_type})"

            linestyle = '--' if is_short else '-'  # Dotted for short, solid for long
            plt.hlines(y=strike, xmin=0, xmax=1, color='black', linestyle=linestyle, linewidth=2.5, label=label)
            
            # --- P AND C LABEL SIZE ---
            # Edit fontsize here to change "P" and "C" size (was 10, now 14)
            plt.text(0.95, strike, option_type, fontsize=14, color='black', ha='right', va='center')

        # --- CURRENT PRICE LINE ---
        # Add blue horizontal line for current price (edit color or linestyle here)
        current_price = group[underlying_price_col].dropna().iloc[0] if not group[underlying_price_col].isna().all() else None
        if current_price is not None:
            plt.hlines(y=current_price, xmin=0, xmax=1, color='blue', linestyle='-', label=f'Underlying Last: {current_price:.2f}')
        else:
            print(f"No valid Underlying Last price found for {symbol} (Expiration: {expiration}).")

        # --- BREAKEVEN PRICE LINE ---
        # Add purple solid line for symbol breakeven (edit color or linestyle here)
        if pd.notna(breakeven):
            plt.hlines(y=breakeven, xmin=0, xmax=1, color='purple', linestyle='-', linewidth=2, label=f"Breakeven {symbol}: {breakeven:.2f}")

        # --- AXIS LABEL FONT SIZE ---
        # Edit fontsize here to adjust x and y label sizes (was 12, now 14)
        plt.xlabel('Option Strikes', fontsize=14)  # Now x-axis is strikes
        plt.ylabel('Underlying Price', fontsize=14)  # Now y-axis is price
        plt.xlim(0, 1)  # Fixed x-axis for clarity (strikes as relative positions)
        plt.xticks([])  # Remove x-axis ticks since it's just a placeholder
        plt.ylim(min_price, max_price)

        # --- LEGEND (KEY) SETTINGS ---
        # Edit loc, bbox_to_anchor, or fontsize here to adjust key position and size (below graph)
        plt.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), title="Key", fontsize=10, title_fontsize=12, frameon=True, ncol=2)

        plt.grid(True, linestyle='--', alpha=0.7)

        # Save the plot to the specified directory
        filename = output_path / f"{symbol}_{expiration.replace('/', '-')}_options.png"
        plt.savefig(filename, bbox_inches='tight')  # Ensure legend fits below
        print(f"Saved plot: {filename}")
        plt.close()

    # Summary table with breakeven calculated per group
    summary_data = []
    for (expiration, symbol), group in grouped:
        breakeven = calculate_symbol_breakeven(group)
        summary_row = {
            'Underlying Symbol': symbol,
            'Expiration': expiration,
            'Option Count': len(group),
            'Min Strike': group['Strike Price'].min(),
            'Max Strike': group['Strike Price'].max(),
            'Breakeven': breakeven
        }
        summary_data.append(summary_row)
    
    summary = pd.DataFrame(summary_data)
    print("\nSummary of Options:")
    print(summary.to_string(index=False))

    # Instructions
    print("\nInstructions:")
    print(f"1. Graphs are saved as PNG files in the directory: {output_path.resolve()}")
    print("2. Black lines: Solid = long calls/puts, Dotted = short calls/puts (horizontal at strikes).")
    print("3. 'C' or 'P' next to each line indicates call or put.")
    print("4. Green shading: Debit spread (Calls: Long low, Short high; Puts: Long high, Short low, same account).")
    print("5. Red shading: Credit spread (Calls: Short low, Long high; Puts: Short high, Long low, same account).")
    print("6. Blue line: Underlying Last (current price of the stock, horizontal).")
    print("7. Purple solid line: Combined breakeven price for all options of the symbol.")
    print("8. Key is below the graph; check the summary table for an overview.")

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Visualize options strikes from a CSV file.")
    parser.add_argument('csv_path', type=str, help="Path to the CSV file containing options data")
    parser.add_argument('--output_dir', type=str, default='output', help="Directory where graphs will be saved (default: 'output')")

    # Parse arguments
    args = parser.parse_args()

    # Call the processing function with the provided CSV path and output directory
    process_and_visualize(args.csv_path, args.output_dir)

if __name__ == "__main__":
    main()