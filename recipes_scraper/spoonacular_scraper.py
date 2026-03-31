#!/usr/bin/env python3
"""
Spoonacular Recipe Scraper - Uses Unified Schema
Scrapes recipes and saves to database via unified schema
"""

import requests
import logging
import os
import time
import re
import json
from typing import Dict, List, Optional
from google import genai
from dotenv import load_dotenv
from consolidated_db_schema import UnifiedRecipeDatabase

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class SpoonacularScraper:
    """Scraper for Spoonacular API"""
    
    DISALLOWED_CHARS = r'["\*]'
    
    def __init__(self, api_key: str, gemini_api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://api.spoonacular.com"
        self.session = requests.Session()
        
        if gemini_api_key:
            self.gemini_client = genai.Client(api_key=gemini_api_key)
        else:
            self.gemini_client = genai.Client()
        
        logger.info("Spoonacular scraper initialized")
    
    def _validate_text(self, text: str, field_name: str = "field") -> str:
        """Remove disallowed characters from text"""
        if not isinstance(text, str):
            return text
        
        if re.search(self.DISALLOWED_CHARS, text):
            logger.debug(f"Removing disallowed characters from {field_name}")
            cleaned = re.sub(self.DISALLOWED_CHARS, '', text)
            return cleaned.strip()
        
        return text
    
    def search_recipes(self, query: str, number: int = 10, offset: int = 0) -> List[Dict]:
        """Search recipes using Spoonacular API"""
        try:
            logger.info(f"Searching recipes for: {query}")
            
            params = {
                'apiKey': self.api_key,
                'query': query,
                'number': number,
                'offset': offset,
                'addRecipeInformation': True,
                'fillIngredients': True
            }
            
            response = self.session.get(
                f"{self.base_url}/recipes/complexSearch",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Found {len(data.get('results', []))} recipes")
                return data.get('results', [])
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                return []
        
        except Exception as e:
            logger.error(f"Error searching recipes: {e}")
            return []
    
    def get_recipe_details(self, recipe_id: int) -> Optional[Dict]:
        """Get detailed recipe information"""
        try:
            logger.info(f"Fetching details for recipe ID: {recipe_id}")
            
            params = {
                'apiKey': self.api_key,
                'includeNutrition': True
            }
            
            response = self.session.get(
                f"{self.base_url}/recipes/{recipe_id}/information",
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"Retrieved recipe details for ID: {recipe_id}")
                return response.json()
            else:
                logger.error(f"Failed to fetch recipe {recipe_id}: {response.status_code}")
                return None
        
        except Exception as e:
            logger.error(f"Error fetching recipe details: {e}")
            return None
    
    def generate_directions_with_gemini(self, recipe_data: Dict) -> Optional[List[str]]:
        """Generate directions using Gemini LLM"""
        try:
            logger.info("Generating directions with Gemini LLM...")
            
            ingredients_list = recipe_data.get('extendedIngredients', [])
            ingredients_text = "\n".join([f"- {ing.get('original', ing.get('name'))}" for ing in ingredients_list[:15]])
            
            # Get existing instructions if available
            existing_instructions = recipe_data.get('analyzedInstructions', [])
            existing_steps = ""
            if existing_instructions:
                for instruction in existing_instructions:
                    for step in instruction.get('steps', []):
                        existing_steps += f"- {step['step']}\n"
            
            prompt = f"""You are a professional chef. Generate or refine clear, numbered cooking directions for this recipe.

RECIPE: {recipe_data.get('title', 'Unknown Recipe')}
SERVINGS: {recipe_data.get('servings', 'Not specified')}
PREP TIME: {recipe_data.get('preparationMinutes', 'Not specified')} minutes
COOK TIME: {recipe_data.get('cookingMinutes', 'Not specified')} minutes

INGREDIENTS:
{ingredients_text}

{'EXISTING INSTRUCTIONS TO ENHANCE:' + chr(10) + existing_steps if existing_steps else 'NO EXISTING INSTRUCTIONS'}

Generate 7-10 clear, actionable cooking steps. Format EXACTLY as numbered list:
1. First step here
2. Second step here
etc.

Each step should be specific about timing, temperatures, and techniques.
Do NOT include any text before or after the numbered steps - ONLY the numbered steps."""

            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            
            directions_text = response.text.strip()
            logger.debug(f"Raw Gemini response:\n{directions_text}\n")
            
            directions = self._parse_directions_from_response(directions_text)
            
            if directions:
                logger.info(f"Successfully generated {len(directions)} direction steps")
                return directions
            else:
                logger.warning("No directions were parsed from Gemini response")
                return None
        
        except Exception as e:
            logger.error(f"Error generating directions: {e}")
            return None
    
    def _parse_directions_from_response(self, text: str) -> List[str]:
        """Parse numbered directions from LLM response"""
        directions = []
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            
            if not line:
                continue
            
            match = re.match(r'^[\*]*(\d+)[.\):\*]*[\*]*\s+(.+)$', line)
            
            if match:
                step_text = match.group(2).strip()
                step_text = re.sub(r'[\*]+$', '', step_text).strip()
                step_text = self._validate_text(step_text, "direction")
                
                if step_text and len(step_text) > 10:
                    directions.append(step_text)
                    logger.debug(f"Parsed direction: {step_text[:60]}...")
        
        return directions
    
    def generate_recipe_analysis(self, recipe_data: Dict) -> Optional[str]:
        """Generate analysis for the recipe"""
        try:
            logger.info("Generating recipe analysis...")
            
            ingredients_list = recipe_data.get('extendedIngredients', [])
            ingredients_str = ", ".join([ing.get('name', '') for ing in ingredients_list[:5]])
            diets = ", ".join(recipe_data.get('diets', [])) or "None"
            
            prompt = f"""Analyze this recipe briefly:

RECIPE: {recipe_data.get('title', 'Unknown')}
SERVINGS: {recipe_data.get('servings', 'N/A')}
READY IN: {recipe_data.get('readyInMinutes', 'N/A')} minutes
HEALTH SCORE: {recipe_data.get('healthScore', 'N/A')}/100

DIETS: {diets}
KEY INGREDIENTS: {ingredients_str}

Provide a brief analysis (3-4 sentences) covering:
1. Difficulty level and time commitment
2. Nutritional highlights
3. Best for what type of meal/occasion
4. Any special notes or tips"""

            response = self.gemini_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
            
            return self._validate_text(response.text.strip(), "recipe_analysis")
        
        except Exception as e:
            logger.error(f"Error generating analysis: {e}")
            return None
    
    def prepare_recipe_data(self, recipe_data: Dict) -> Dict:
        """Prepare recipe data for database insertion"""
        try:
            # Prepare ingredients data
            ingredients = recipe_data.get('extendedIngredients', [])
            
            # Prepare directions data - combine original and AI-generated
            directions_list = []
            instructions = recipe_data.get('analyzedInstructions', [])
            
            if instructions:
                for instruction_group in instructions:
                    for step in instruction_group.get('steps', []):
                        directions_list.append({
                            'step_number': step.get('number', 0),
                            'instruction': step.get('step'),
                            'source': 'original',
                            'equipment': [e.get('name', '') for e in step.get('equipment', [])],
                            'ingredients': [i.get('name', '') for i in step.get('ingredients', [])]
                        })
            
            # Generate AI directions if none exist
            ai_directions = None
            if not directions_list:
                logger.info("No original instructions found, generating with AI...")
                ai_directions = self.generate_directions_with_gemini(recipe_data)
                
                if ai_directions:
                    for idx, direction in enumerate(ai_directions, 1):
                        directions_list.append({
                            'step_number': idx,
                            'instruction': direction,
                            'source': 'ai_generated'
                        })
                    logger.info(f"Generated {len(ai_directions)} AI directions")
            
            # Prepare nutrition data
            nutrition = recipe_data.get('nutrition', {})
            nutrients = nutrition.get('nutrients', [])
            
            # Generate analysis
            analysis = self.generate_recipe_analysis(recipe_data)
            
            # Prepare data dictionary matching schema expectations
            prepared_data = {
                'id': recipe_data.get('id'),
                'spoonacular_id': recipe_data.get('id'),
                'title': recipe_data.get('title'),
                'image_url': recipe_data.get('image'),
                'image_type': recipe_data.get('imageType'),
                'source_url': recipe_data.get('sourceUrl'),
                'summary': recipe_data.get('summary'),
                'cuisines': recipe_data.get('cuisines', []),
                'dish_types': recipe_data.get('dishTypes', []),
                'servings': recipe_data.get('servings'),
                'ready_in_minutes': recipe_data.get('readyInMinutes'),
                'prep_minutes': recipe_data.get('preparationMinutes'),
                'cook_minutes': recipe_data.get('cookingMinutes'),
                'aggregated_likes': recipe_data.get('aggregateLikes', 0),
                'health_score': recipe_data.get('healthScore', 0),
                'diets': recipe_data.get('diets', []),
                'source_name': recipe_data.get('sourceName'),
                'ingredients': ingredients,
                'directions': directions_list,
                'nutrition': nutrients[:20] if nutrients else [],
                'is_vegetarian': recipe_data.get('vegetarian', False),
                'is_vegan': recipe_data.get('vegan', False),
                'is_gluten_free': recipe_data.get('glutenFree', False),
                'is_dairy_free': recipe_data.get('dairyFree', False),
                'is_paleo': recipe_data.get('paleo', False),
                'is_whole30': recipe_data.get('whole30', False),
                'is_very_healthy': recipe_data.get('veryHealthy', False),
                'is_cheap': recipe_data.get('cheap', False),
                'is_very_popular': recipe_data.get('veryPopular', False),
                'ai_analysis': analysis,
                'ai_generated_directions': ai_directions
            }
            
            return prepared_data
            
        except Exception as e:
            logger.error(f"Error preparing recipe data: {e}")
            return None


def main():
    print("\n" + "="*80)
    print("SPOONACULAR RECIPE SCRAPER - USING UNIFIED SCHEMA")
    print("="*80)
    print("\nFeatures:")
    print("  - Search recipes using Spoonacular API")
    print("  - AI-generated directions using Gemini LLM")
    print("  - Saves to unified database schema")
    print("  - Auto-syncs to common tables via triggers")
    print("\n" + "="*80)
    
    # Get API keys
    spoonacular_api_key = os.getenv('SPOONACULAR_API_KEY')
    if not spoonacular_api_key:
        spoonacular_api_key = input("Enter Spoonacular API Key: ").strip()
    
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        gemini_api_key = input("Enter Gemini API Key (optional, press Enter to skip): ").strip() or None
    
    # Database configuration
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', 'localhost'),
        'database': os.getenv('DB_NAME', 'recipes_db'),
        'user': os.getenv('DB_USER', 'postgres'),
        'password': os.getenv('DB_PASSWORD', 'Ah72n):(:'),
        'port': int(os.getenv('DB_PORT', 5432))
    }
    
    # Initialize with db_config parameter
    db = UnifiedRecipeDatabase(DB_CONFIG)
    scraper = SpoonacularScraper(spoonacular_api_key, gemini_api_key)
    
    try:
        # Connect to database
        db.connect()
        
        # Get search query
        query = input("\nEnter recipe search query (e.g., 'pasta', 'vegetarian'): ").strip()
        if not query:
            query = "pasta"
        
        try:
            number = int(input("How many recipes to fetch? (default 5): ") or "5")
        except:
            number = 5
        
        # Search recipes
        recipes = scraper.search_recipes(query, number=number)
        
        if not recipes:
            logger.error("No recipes found")
            return
        
        logger.info(f"Found {len(recipes)} recipes, fetching detailed info...")
        
        saved_count = 0
        skipped_count = 0
        failed_count = 0
        
        for idx, recipe_summary in enumerate(recipes, 1):
            print(f"\n[{idx}/{len(recipes)}] Processing: {recipe_summary.get('title', 'Unknown')}")
            
            # Get full details
            recipe_id = recipe_summary.get('id')
            recipe_details = scraper.get_recipe_details(recipe_id)
            
            if recipe_details:
                # Prepare data
                prepared_data = scraper.prepare_recipe_data(recipe_details)
                
                if prepared_data:
                    # Save to database using unified schema
                    result = db.save_spoonacular_recipe(prepared_data)
                    
                    if result:
                        saved_count += 1
                        print(f"✓ Saved successfully (DB ID: {result})")
                    else:
                        skipped_count += 1
                        print(f"✗ Already exists or failed to save")
                else:
                    failed_count += 1
                    print(f"✗ Failed to prepare data")
            else:
                failed_count += 1
                print(f"✗ Failed to fetch details")
            
            # Rate limiting
            time.sleep(1)
        
        print("\n" + "="*80)
        print(f"SCRAPING COMPLETE!")
        print(f"Saved: {saved_count} | Skipped: {skipped_count} | Failed: {failed_count}")
        print(f"Total: {saved_count + skipped_count + failed_count}/{len(recipes)}")
        print("="*80)
        
        # Show database stats
        stats = db.get_database_stats()
        if stats:
            print("\n📊 DATABASE STATISTICS:")
            for key, value in stats.items():
                print(f"  {key}: {value}")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        db.close()


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
