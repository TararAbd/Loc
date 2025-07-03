
from flask import Flask, render_template, request, jsonify
import requests
import re
import asyncio
import aiohttp
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import logging
from functools import lru_cache
from typing import Optional, Dict, Any, List

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
MAX_WORKERS = 10  # Maximum number of concurrent requests
REQUEST_TIMEOUT = 30  # Timeout for API requests in seconds
RATE_LIMIT_DELAY = 0.1  # Delay between requests to avoid overwhelming the API

class PhoneNumberChecker:
    def __init__(self, max_workers: int = MAX_WORKERS, timeout: int = REQUEST_TIMEOUT):
        self.max_workers = max_workers
        self.timeout = timeout
        self.session = requests.Session()
        # Configure session for better performance
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    @staticmethod
    @lru_cache(maxsize=1000)
    def format_number(user_input: str) -> Optional[str]:
        """
        Format phone number with caching for better performance.
        """
        if not user_input or not isinstance(user_input, str):
            return None
            
        # Remove all non-digit characters except +
        number = re.sub(r'[^\d+]', '', user_input.strip())
        
        # Validate that we have at least some digits
        if not re.search(r'\d', number):
            return None
            
        if number.startswith('03') and len(number) > 10:
            return number[1:]  # Remove the leading '0'
        elif number.startswith('+92') and len(number) > 12:
            return number[3:]  # Remove the leading '+92'
        elif number.startswith('92') and len(number) > 11:
            return number[2:]  # Remove the leading '92'
        elif number.startswith('3') and len(number) >= 10:
            return number  # Already in correct format
        else:
            return None  # Invalid format

    def check_single_number(self, phone_number: str) -> Dict[str, Any]:
        """
        Check a single phone number.
        """
        formatted_number = self.format_number(phone_number)
        
        if not formatted_number or len(formatted_number) < 10:
            return {
                'success': False,
                'error': 'Invalid number format or number is too short.',
                'phone_number': phone_number
            }
        
        url = f"https://anoncyberwarrior.com/acwtools.php?num={formatted_number}"
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            try:
                data = response.json()
                return {
                    'success': True,
                    'data': data,
                    'phone_number': phone_number,
                    'formatted_number': formatted_number
                }
            except ValueError as e:
                logger.error(f"JSON parsing error for {phone_number}: {e}")
                return {
                    'success': False,
                    'error': 'Failed to parse JSON response.',
                    'phone_number': phone_number
                }
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout error for {phone_number}")
            return {
                'success': False,
                'error': 'Request timeout.',
                'phone_number': phone_number
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {phone_number}: {e}")
            return {
                'success': False,
                'error': f'Request failed: {str(e)}',
                'phone_number': phone_number
            }
        except Exception as e:
            logger.error(f"Unexpected error for {phone_number}: {e}")
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}',
                'phone_number': phone_number
            }

    def check_multiple_numbers(self, phone_numbers: List[str]) -> List[Dict[str, Any]]:
        """
        Check multiple phone numbers concurrently.
        """
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_number = {
                executor.submit(self.check_single_number, number): number 
                for number in phone_numbers
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_number):
                try:
                    result = future.result()
                    results.append(result)
                    # Add small delay to avoid overwhelming the API
                    time.sleep(RATE_LIMIT_DELAY)
                except Exception as e:
                    phone_number = future_to_number[future]
                    logger.error(f"Error processing {phone_number}: {e}")
                    results.append({
                        'success': False,
                        'error': f'Processing error: {str(e)}',
                        'phone_number': phone_number
                    })
        
        return results

# Global instance
phone_checker = PhoneNumberChecker()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check', methods=['POST'])
def check_number():
    """
    Handle single phone number check.
    """
    try:
        user_input = request.form.get('phone_number')
        if not user_input:
            return jsonify({'success': False, 'error': 'Phone number is required.'}), 400
            
        result = phone_checker.check_single_number(user_input)
        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Error in check_number: {e}")
        return jsonify({'success': False, 'error': 'Internal server error.'}), 500

@app.route('/check_multiple', methods=['POST'])
def check_multiple_numbers():
    """
    Handle multiple phone number checks concurrently.
    """
    try:
        data = request.get_json()
        if not data or 'phone_numbers' not in data:
            return jsonify({'success': False, 'error': 'phone_numbers array is required.'}), 400
            
        phone_numbers = data['phone_numbers']
        if not isinstance(phone_numbers, list):
            return jsonify({'success': False, 'error': 'phone_numbers must be an array.'}), 400
            
        if len(phone_numbers) == 0:
            return jsonify({'success': False, 'error': 'At least one phone number is required.'}), 400
            
        if len(phone_numbers) > 100:  # Limit to prevent abuse
            return jsonify({'success': False, 'error': 'Maximum 100 phone numbers allowed.'}), 400
            
        start_time = time.time()
        results = phone_checker.check_multiple_numbers(phone_numbers)
        end_time = time.time()
        
        # Calculate summary statistics
        successful_checks = sum(1 for result in results if result['success'])
        failed_checks = len(results) - successful_checks
        
        response = {
            'success': True,
            'results': results,
            'summary': {
                'total_numbers': len(phone_numbers),
                'successful_checks': successful_checks,
                'failed_checks': failed_checks,
                'processing_time': round(end_time - start_time, 2)
            }
        }
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error in check_multiple_numbers: {e}")
        return jsonify({'success': False, 'error': 'Internal server error.'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    """
    return jsonify({'status': 'healthy', 'timestamp': time.time()})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found.'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'success': False, 'error': 'Method not allowed.'}), 405

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'success': False, 'error': 'Internal server error.'}), 500

if __name__ == "__main__":
    # For production, use a proper WSGI server like Gunicorn
    app.run(debug=True, threaded=True, host='0.0.0.0', port=5000)
