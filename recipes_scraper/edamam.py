#!/usr/bin/env python3
"""
Edamam Recipe Scraper - Works with Unified Database Schema
Saves to edamam_recipes table, auto-syncs to common tables
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
import time
import re
import logging
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Import the unified database schema
try:
    from consolidated_db_schema import UnifiedRecipeDatabase, DB_CONFIG
except ImportError:
    print("ERROR: unified_recipe_db.py not found!")
    print("Please ensure unified_recipe_db.py is in the same directory.")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class EdamamRecipeScraperWithGemini:
    DISALLOWED_CHARS = r'["\*]'
    
    def __init__(self, headless=True, gemini_api_key=None):
        self.chrome_options = Options()
        if headless:
            self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--no-sandbox")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--window-size=1920,1080")
        self.driver = None
        self.wait = None
        
        if gemini_api_key:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
        else:
            self.gemini_client = genai.Client()
        
        logger.info("Gemini LLM client initialized")

    def _validate_text(self, text, field_name="field"):
        """Remove disallowed characters from text"""
        if not isinstance(text, str):
            return text
        
        if re.search(self.DISALLOWED_CHARS, text):
            logger.debug(f"Removing disallowed characters from {field_name}")
            cleaned = re.sub(self.DISALLOWED_CHARS, '', text)
            return cleaned.strip()
        
        return text

    def _validate_list(self, items, field_name="items"):
        """Validate and clean list items"""
        if not isinstance(items, list):
            return items
        
        cleaned = []
        for item in items:
            if isinstance(item, str):
                cleaned_item = self._validate_text(item, f"{field_name} item")
                if cleaned_item:
                    cleaned.append(cleaned_item)
            else:
                cleaned.append(item)
        
        return cleaned

    def _parse_directions_from_response(self, text):
        """Parse numbered directions from LLM response"""
        directions = []
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            
            if not line:
                continue
            
            # Match numbered steps
            match = re.match(r'^[\*]*(\d+)[.\):\*]*[\*]*\s+(.+)$', line)
            
            if match:
                step_text = match.group(2).strip()
                step_text = re.sub(r'[\*]+$', '', step_text).strip()
                step_text = self._validate_text(step_text, "direction")
                
                if step_text and len(step_text) > 10:
                    directions.append(step_text)
                    logger.debug(f"Parsed direction {len(directions)}: {step_text[:60]}...")
        
        return directions

    def _generate_directions_with_retry(self, recipe_data, attempt=1, max_attempts=3):
        """Generate directions with retry logic"""
        
        if attempt > max_attempts:
            logger.error(f"Failed to generate directions after {max_attempts} attempts")
            return None
        
        try:
            logger.info(f"Generating directions (attempt {attempt}/{max_attempts})...")
            
            ingredients_text = "\n".join([f"- {ing}" for ing in recipe_data.get('ingredients', [])[:15]])
            
            # Different prompts based on attempt
            if attempt == 1:
                prompt = f"""You are a professional chef. Generate clear, numbered cooking directions.

RECIPE: {recipe_data.get('title', 'Unknown Recipe')}
SERVINGS: {recipe_data.get('servings', 'Not specified')}

INGREDIENTS:
{ingredients_text}

TIMES:
- Prep: {recipe_data.get('prep_time', 'Not specified')}
- Cook: {recipe_data.get('cook_time', 'Not specified')}
- Total: {recipe_data.get('total_time', 'Not specified')}

Generate 6-10 clear, actionable cooking steps. Format EXACTLY as numbered list:
1. First step
2. Second step
3. Third step

Do NOT include any text before or after the numbered steps - ONLY the numbered steps."""
            
            elif attempt == 2:
                prompt = f"""Generate cooking steps for: {recipe_data.get('title', 'Unknown')}

Ingredients: {', '.join(recipe_data.get('ingredients', [])[:10])}

Output EXACTLY 7 steps in this format - no other text:
1. Step one
2. Step two
3. Step three
4. Step four
5. Step five
6. Step six
7. Step seven"""
            
            else:
                prompt = f"""Steps to make {recipe_data.get('title', 'Unknown')}:
1."""
            
            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            
            directions_text = response.text.strip()
            logger.debug(f"Raw Gemini response (attempt {attempt}):\n{directions_text}\n")
            
            directions = self._parse_directions_from_response(directions_text)
            
            if directions and len(directions) >= 5:
                logger.info(f"✅ Generated {len(directions)} direction steps on attempt {attempt}")
                return directions
            elif directions and len(directions) >= 3:
                logger.warning(f"Generated only {len(directions)} steps but using them")
                return directions
            else:
                logger.warning(f"Attempt {attempt}: Got {len(directions)} steps, retrying...")
                if attempt < max_attempts:
                    time.sleep(2)
                    return self._generate_directions_with_retry(recipe_data, attempt + 1, max_attempts)
                return None
                
        except Exception as e:
            logger.error(f"Error on attempt {attempt}: {e}")
            if attempt < max_attempts:
                time.sleep(2)
                return self._generate_directions_with_retry(recipe_data, attempt + 1, max_attempts)
            return None

    def generate_recipe_analysis(self, recipe_data):
        """Generate analysis for the recipe"""
        try:
            logger.info("Generating recipe analysis...")
            
            ingredients_text = "\n".join(recipe_data.get('ingredients', [])[:5])
            diet_labels = ", ".join(recipe_data.get('diet_labels', [])) or "None"
            health_labels = ", ".join(recipe_data.get('health_labels', [])) or "None"
            
            prompt = f"""Analyze this recipe briefly:

RECIPE: {recipe_data.get('title', 'Unknown')}
SOURCE: {recipe_data.get('source_name', 'Unknown')}
SERVINGS: {recipe_data.get('servings', 'N/A')}
CALORIES/SERVING: {recipe_data.get('calories_per_serving', 'N/A')}

DIET LABELS: {diet_labels}
HEALTH LABELS: {health_labels}

Key Ingredients: {ingredients_text}

Provide a brief analysis (3-4 sentences) covering:
1. Difficulty level and time commitment
2. Nutritional highlights
3. Best for what type of meal/occasion"""

            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            
            return self._validate_text(response.text.strip(), "recipe_analysis")
            
        except Exception as e:
            logger.error(f"Error generating recipe analysis: {e}")
            return None

    def start_driver(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 10)

    def extract_recipe_id(self, url):
        pattern = r'recipe=([^/&]+)'
        match = re.search(pattern, url)
        return match.group(1) if match else None

    def scrape_recipe(self, url):
        if not self.driver:
            self.start_driver()
        
        try:
            logger.info(f"Loading recipe page: {url}")
            self.driver.get(url)
            time.sleep(3)
            
            recipe_data = {
                'recipe_id': self.extract_recipe_id(url),
                'source_url': url
            }
            
            # Scrape basic info
            basic_info = self._scrape_basic_info()
            recipe_data.update(basic_info)
            
            # Scrape ingredients
            recipe_data['ingredients'] = self._validate_list(
                self._scrape_ingredients(), "ingredients"
            )
            logger.info(f"Scraped {len(recipe_data['ingredients'])} ingredients")
            
            # Scrape nutrition
            recipe_data['nutrition'] = self._scrape_nutrition()
            logger.info(f"Scraped {len(recipe_data['nutrition'])} nutrition entries")
            
            # Scrape labels
            labels = self._scrape_labels()
            recipe_data.update(labels)
            logger.info(f"Scraped {len(recipe_data['diet_labels'])} diet labels, {len(recipe_data['health_labels'])} health labels")
            
            # Generate directions
            logger.info("=" * 80)
            logger.info("GENERATING DIRECTIONS WITH GEMINI LLM...")
            logger.info("=" * 80)
            directions = self._generate_directions_with_retry(recipe_data)
            
            if directions:
                recipe_data['directions'] = directions
                logger.info(f"✅ Added {len(directions)} AI-generated directions")
                for i, direction in enumerate(directions, 1):
                    logger.info(f"  {i}. {direction[:70]}...")
            else:
                logger.warning("⚠️ Could not generate directions")
                recipe_data['directions'] = []
            
            # Generate analysis
            analysis = self.generate_recipe_analysis(recipe_data)
            recipe_data['recipe_analysis'] = analysis
            
            # Log summary
            logger.info("\n" + "="*80)
            logger.info("SCRAPED RECIPE DATA SUMMARY")
            logger.info("="*80)
            logger.info(f"Title: {recipe_data.get('title', 'N/A')}")
            logger.info(f"Recipe ID: {recipe_data.get('recipe_id', 'N/A')}")
            logger.info(f"Ingredients: {len(recipe_data.get('ingredients', []))}")
            logger.info(f"Directions: {len(recipe_data.get('directions', []))} (AI)")
            logger.info(f"Nutrition: {len(recipe_data.get('nutrition', {}))}")
            logger.info(f"Diet labels: {len(recipe_data.get('diet_labels', []))}")
            logger.info(f"Health labels: {len(recipe_data.get('health_labels', []))}")
            logger.info("="*80 + "\n")
            
            return recipe_data
            
        except Exception as e:
            logger.error(f"Error scraping recipe: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _scrape_basic_info(self):
        data = {}
        
        try:
            title_element = self.driver.find_element(By.ID, "recipe-title")
            data['title'] = self._validate_text(title_element.text.strip(), "title")
            
            try:
                img_element = self.driver.find_element(By.CSS_SELECTOR, "#recipe-image img")
                data['image_url'] = img_element.get_attribute('src')
            except:
                data['image_url'] = None
            
            try:
                source_element = self.driver.find_element(By.CSS_SELECTOR, "#recipe-source .source-link span")
                data['source_name'] = self._validate_text(source_element.text.strip(), "source_name")
            except:
                data['source_name'] = None
            
            try:
                servings_element = self.driver.find_element(By.ID, "serv")
                data['servings'] = int(servings_element.get_attribute('value'))
            except:
                data['servings'] = None
            
            try:
                calories_element = self.driver.find_element(By.ID, "kcal-val")
                data['calories_per_serving'] = int(calories_element.text.strip())
            except:
                data['calories_per_serving'] = None
            
            try:
                time_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='time']")
                for elem in time_elements:
                    text = elem.text.lower()
                    if 'total' in text:
                        time_match = re.search(r'(\d+\s*(?:min|hour|hr))', text, re.IGNORECASE)
                        if time_match:
                            data['total_time'] = time_match.group(1)
                    elif 'prep' in text:
                        time_match = re.search(r'(\d+\s*(?:min|hour|hr))', text, re.IGNORECASE)
                        if time_match:
                            data['prep_time'] = time_match.group(1)
                    elif 'cook' in text:
                        time_match = re.search(r'(\d+\s*(?:min|hour|hr))', text, re.IGNORECASE)
                        if time_match:
                            data['cook_time'] = time_match.group(1)
            except:
                pass
            
            logger.info(f"Scraped basic info: {data.get('title', 'Unknown')}")
            return data
            
        except Exception as e:
            logger.error(f"Error scraping basic info: {e}")
            return data

    def _scrape_ingredients(self):
        try:
            ingredients = []
            ingredient_elements = self.driver.find_elements(By.CSS_SELECTOR, "#recipe-ingredients ul li")
            
            for element in ingredient_elements:
                ingredient_text = element.text.strip()
                if ingredient_text:
                    ingredients.append(ingredient_text)
            
            return ingredients
            
        except Exception as e:
            logger.error(f"Error scraping ingredients: {e}")
            return []

    def _scrape_nutrition(self):
        nutrition_data = {}
        
        try:
            nutrition_elements = self.driver.find_elements(By.CSS_SELECTOR, "#nutrition-list .line")
            
            for element in nutrition_elements:
                try:
                    name_element = element.find_element(By.TAG_NAME, "h2")
                    nutrient_name = name_element.text.strip()
                    
                    if not nutrient_name:
                        continue
                    
                    amount = None
                    unit = None
                    daily_value = None
                    
                    try:
                        size_element = element.find_element(By.CSS_SELECTOR, ".size")
                        size_text = size_element.text.strip()
                        
                        if size_text:
                            match = re.match(r'^\s*([\d,]+(?:\.\d+)?)\s*([a-zA-Zµ%]+)\s*$', size_text)
                            
                            if match:
                                amount_str = match.group(1).replace(',', '')
                                amount = float(amount_str) if amount_str else 0.0
                                unit = match.group(2)
                    except NoSuchElementException:
                        pass
                    
                    try:
                        percent_element = element.find_element(By.CSS_SELECTOR, ".percent")
                        percent_text = percent_element.text.strip().replace('%', '').strip()
                        
                        if percent_text and percent_text.replace('<', '').isdigit():
                            daily_value = int(percent_text.replace('<', ''))
                    except NoSuchElementException:
                        pass
                    
                    clean_name = nutrient_name.lower()
                    clean_name = re.sub(r'[^\w\s]', '_', clean_name)
                    clean_name = re.sub(r'\s+', '_', clean_name)
                    clean_name = re.sub(r'_+', '_', clean_name).strip('_')
                    
                    nutrition_data[clean_name] = {
                        'amount': amount,
                        'unit': unit,
                        'daily_value_percent': daily_value
                    }
                    
                except Exception:
                    continue
            
            return nutrition_data
            
        except Exception as e:
            logger.error(f"Error scraping nutrition: {e}")
            return {}

    def _scrape_labels(self):
        try:
            labels_data = {
                'diet_labels': [],
                'health_labels': []
            }
            
            try:
                label_container = self.driver.find_element(By.ID, "nutrition-labels")
                label_elements = label_container.find_elements(By.TAG_NAME, "a")
                
                for element in label_elements:
                    try:
                        label_text = element.text.strip()
                        href = element.get_attribute('href')
                        
                        if not label_text or not href:
                            continue
                        
                        label_text = self._validate_text(label_text, "label")
                        
                        if '/diet=' in href.lower():
                            if label_text not in labels_data['diet_labels']:
                                labels_data['diet_labels'].append(label_text)
                        elif '/health=' in href.lower():
                            if label_text not in labels_data['health_labels']:
                                labels_data['health_labels'].append(label_text)
                                
                    except Exception:
                        continue
                        
            except NoSuchElementException:
                pass
            
            return labels_data
            
        except Exception as e:
            logger.error(f"Error scraping labels: {e}")
            return {'diet_labels': [], 'health_labels': []}

    def close(self):
        if self.driver:
            self.driver.quit()

    def __enter__(self):
        self.start_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    print("\n" + "="*80)
    print("EDAMAM RECIPE SCRAPER - UNIFIED DATABASE")
    print("="*80)
    print("\n📋 Features:")
    print("  • AI-generated cooking directions (Gemini LLM)")
    print("  • Saves to edamam_recipes table")
    print("  • Auto-syncs to common tables via triggers")
    print("  • Normalized data in recipe_ingredients, recipe_directions, etc.")
    print("\n🔄 Workflow:")
    print("  1. Scrape recipe from Edamam")
    print("  2. Generate AI directions")
    print("  3. Save to edamam_recipes table")
    print("  4. Trigger auto-syncs to common tables")
    print("\n" + "="*80)
    
    # Get URL
    url = input("\nEnter Edamam recipe URL: ").strip()
    if not url:
        url = "https://www.edamam.com/results/recipe/?recipe=grilled-salmon-kebabs-with-kale-tabbouleh-282fb429192a415886cb109357290111/search=salad"
    
    # Initialize database
    db = UnifiedRecipeDatabase(DB_CONFIG)
    
    try:
        logger.info("Connecting to database...")
        db.connect()
        logger.info("✅ Database connected")
        
        # Show current stats
        stats = db.get_database_stats()
        print("\n📊 Current Database Stats:")
        for key, value in stats.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for sub_key, sub_value in value.items():
                    print(f"    {sub_key}: {sub_value}")
            else:
                print(f"  {key}: {value}")
        
        print(f"\n🎯 Target URL: {url}")
        response = input("Start scraping? (y/n): ").lower()
        if response != 'y':
            print("Cancelled.")
            return
        
        print("\n🚀 Starting scrape...\n")
        
        # Scrape recipe
        with EdamamRecipeScraperWithGemini(headless=False) as scraper:
            recipe_data = scraper.scrape_recipe(url)
            
            if recipe_data:
                logger.info("💾 Saving recipe to database...")
                recipe_id = db.save_edamam_recipe(recipe_data)
                
                if recipe_id:
                    print("\n" + "="*80)
                    print("✅ RECIPE SAVED SUCCESSFULLY!")
                    print("="*80)
                    print(f"📝 Title: {recipe_data.get('title', 'N/A')}")
                    print(f"🆔 Edamam ID: {recipe_id}")
                    print(f"🥘 Ingredients: {len(recipe_data.get('ingredients', []))}")
                    print(f"📋 Directions: {len(recipe_data.get('directions', []))} (AI-generated)")
                    print(f"🍎 Nutrition: {len(recipe_data.get('nutrition', {}))}")
                    print(f"🏷️ Tags: {len(recipe_data.get('diet_labels', []))} diet + {len(recipe_data.get('health_labels', []))} health")
                    print(f"\n💾 Saved to: edamam_recipes")
                    print(f"🔄 Auto-synced to: recipes, recipe_ingredients, recipe_directions, recipe_nutrition, recipe_tags")
                    
                    if recipe_data.get('directions'):
                        print(f"\n📋 AI-Generated Directions:")
                        for i, direction in enumerate(recipe_data.get('directions', []), 1):
                            print(f"  {i}. {direction}")
                    
                    print("="*80)
                else:
                    logger.error("❌ Failed to save recipe")
            else:
                logger.error("❌ Failed to scrape recipe")
        
        # Show updated stats
        stats = db.get_database_stats()
        print("\n📊 Updated Database Stats:")
        for key, value in stats.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for sub_key, sub_value in value.items():
                    print(f"    {sub_key}: {sub_value}")
            else:
                print(f"  {key}: {value}")
        
        print("\n✅ SCRAPING COMPLETE!")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")