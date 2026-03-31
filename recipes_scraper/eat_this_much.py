#!/usr/bin/env python3
"""
Enhanced EatThisMuch Recipe Scraper with Consolidated Database Schema
Includes pagination support, comprehensive data extraction, and automatic total_time calculation
UPDATED: Now uses consolidated_db_schema.py with total_time calculation
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urljoin
import time
import logging
from typing import Dict, List, Optional, Tuple, Any

# Import the consolidated database schema
try:
    from consolidated_db_schema import UnifiedRecipeDatabase, DB_CONFIG
except ImportError:
    print("ERROR: consolidated_db_schema.py not found!")
    print("Please ensure consolidated_db_schema.py is in the same directory.")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EatThisMuchScraperConsolidated:
    """EatThisMuch scraper using consolidated database schema"""
    
    def __init__(self, db_instance: UnifiedRecipeDatabase):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.db = db_instance
    
    def _parse_time_to_minutes(self, time_str: str) -> Optional[int]:
        """
        Convert time string to minutes.
        Handles formats like: "30 min", "1 hr 30 min", "1h 30m", "90 minutes"
        
        Args:
            time_str: Time string to parse
            
        Returns:
            Total minutes as integer, or None if parsing fails
        """
        if not time_str:
            return None
        
        time_str = time_str.lower().strip()
        total_minutes = 0
        
        # Find hours
        hour_match = re.search(r'(\d+\.?\d*)\s*(?:hour|hr|h)s?', time_str)
        if hour_match:
            total_minutes += int(float(hour_match.group(1)) * 60)
        
        # Find minutes
        min_match = re.search(r'(\d+\.?\d*)\s*(?:minute|min|m)s?', time_str)
        if min_match:
            total_minutes += int(float(min_match.group(1)))
        
        return total_minutes if total_minutes > 0 else None
    
    def _calculate_total_time(self, times: Dict[str, str]) -> Dict[str, str]:
        """
        Calculate total_time from prep_time and cook_time if not present.
        Modifies the times dictionary in place.
        
        Args:
            times: Dictionary containing time information
            
        Returns:
            Updated times dictionary with calculated total_time
        """
        # If total_time already exists, return as is
        if times.get('total_time'):
            logger.debug(f"   Total time already exists: {times['total_time']}")
            return times
        
        # Try to calculate from prep_time and cook_time
        prep_minutes = self._parse_time_to_minutes(times.get('prep_time', ''))
        cook_minutes = self._parse_time_to_minutes(times.get('cook_time', ''))
        
        logger.debug(f"   Prep minutes: {prep_minutes}, Cook minutes: {cook_minutes}")
        
        # Only calculate if we have at least one valid time
        if prep_minutes is not None or cook_minutes is not None:
            total_minutes = (prep_minutes or 0) + (cook_minutes or 0)
            
            if total_minutes > 0:
                # Format the total time
                if total_minutes < 60:
                    times['total_time'] = f"{total_minutes} min"
                else:
                    hours = total_minutes // 60
                    mins = total_minutes % 60
                    if mins == 0:
                        times['total_time'] = f"{hours} hr{'s' if hours > 1 else ''}"
                    else:
                        times['total_time'] = f"{hours} hr{'s' if hours > 1 else ''} {mins} min"
                
                logger.info(f"   ✓ Calculated total_time: {times['total_time']} (from prep + cook)")
        
        return times
    
    def get_recipe_links_with_pagination(self, base_url: str, max_recipes: int = 50, max_pages: int = 10) -> List[str]:
        """Get recipe links from multiple pages using pagination"""
        recipe_links = []
        current_url = base_url
        page_count = 0
        
        logger.info(f"🔍 Starting pagination crawl from: {base_url}")
        
        while current_url and len(recipe_links) < max_recipes and page_count < max_pages:
            try:
                page_count += 1
                logger.info(f"📄 Fetching page {page_count}: {current_url}")
                
                response = self.session.get(current_url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                page_links = self._extract_recipe_links_from_page(soup, current_url)
                logger.info(f"   ✓ Found {len(page_links)} recipe links on page {page_count}")
                
                recipe_links.extend(page_links)
                
                next_url = self._find_next_page_url(soup, current_url)
                if next_url:
                    logger.info(f"   ➡️  Next page found: {next_url[:80]}...")
                    current_url = next_url
                    time.sleep(2)
                else:
                    logger.info("   ⛔ No more pages found")
                    break
                    
            except Exception as e:
                logger.error(f"❌ Error fetching page {page_count}: {e}")
                break
        
        unique_links = list(dict.fromkeys(recipe_links))[:max_recipes]
        logger.info(f"✅ Collected {len(unique_links)} unique recipe links from {page_count} pages")
        
        return unique_links
    
    def _extract_recipe_links_from_page(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract recipe links from a single page"""
        recipe_links = []
        
        all_links = soup.find_all('a', href=True)
        for link in all_links:
            href = link.get('href')
            if href and self._is_recipe_url(href):
                full_url = urljoin(base_url, href)
                recipe_links.append(full_url)
        
        recipe_selectors = [
            'a[href*="/calories/"]',
            'a[href*="/food/"]',
            '.recipe-card a',
            '.food-item a',
        ]
        
        for selector in recipe_selectors:
            links = soup.select(selector)
            for link in links:
                href = link.get('href')
                if href and self._is_recipe_url(href):
                    full_url = urljoin(base_url, href)
                    if full_url not in recipe_links:
                        recipe_links.append(full_url)
        
        return recipe_links
    
    def _is_recipe_url(self, url: str) -> bool:
        """Check if a URL looks like a recipe URL"""
        if not url:
            return False
        
        recipe_patterns = [
            r'/calories/[^/]+\-\d+$',
            r'/food/[^/]+\-\d+$',
        ]
        
        for pattern in recipe_patterns:
            if re.search(pattern, url):
                return True
        
        return False
    
    def _find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Find the next page URL from pagination elements"""
        
        more_results_selectors = [
            'a[href*="after="]',
            '.more-results a',
            'a._button_rkz8n_1',
        ]
        
        for selector in more_results_selectors:
            try:
                link = soup.select_one(selector)
                if link:
                    href = link.get('href')
                    if href:
                        return urljoin(current_url, href)
            except Exception as e:
                logger.debug(f"Error with selector {selector}: {e}")
                continue
        
        all_links = soup.find_all('a', href=True)
        for link in all_links:
            href = link.get('href')
            if href and 'after=' in href and 'browse' in href:
                return urljoin(current_url, href)
        
        return None
    
    def scrape_recipe(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape a single recipe with comprehensive data extraction"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract times and calculate total_time
            times = self._extract_times(soup)
            times = self._calculate_total_time(times)
            
            recipe_data = {
                'url': url,
                'title': self._extract_title(soup),
                'image_url': self._extract_image(soup, url),
                'description': self._extract_description(soup),
                'meta_description': self._extract_meta_description(soup),
                'og_description': self._extract_og_description(soup),
                'servings': self._extract_servings(soup),
                'times': times,
                'nutrition': self._extract_nutrition(soup),
                'ingredients': self._extract_ingredients(soup),
                'instructions': self._extract_instructions(soup),
                'tags': self._extract_tags(soup),
                'recipe_info': self._extract_recipe_info(soup)
            }
            
            # Debug output
            logger.debug(f"=== SCRAPED DATA DEBUG ===")
            logger.debug(f"Title: {recipe_data['title']}")
            logger.debug(f"Ingredients: {len(recipe_data['ingredients'])} found")
            logger.debug(f"Instructions: {len(recipe_data['instructions'])} found")
            logger.debug(f"Nutrition: {len(recipe_data['nutrition'])} entries")
            logger.debug(f"Tags: {len(recipe_data['tags'])} found")
            logger.debug(f"Times: {recipe_data['times']}")
            logger.debug(f"=========================")
            
            return recipe_data
            
        except Exception as e:
            logger.error(f"❌ Error scraping recipe {url}: {e}")
            return None
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract recipe title"""
        for tag_name in ['h1', 'h2', 'title']:
            elements = soup.find_all(tag_name)
            for element in elements:
                text = element.get_text(strip=True)
                if text and len(text) > 3:
                    if 'eatthismuch' in text.lower():
                        text = text.split('|')[0].split('-')[0].strip()
                    return text
        return "Unknown Recipe"
    
    def _extract_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Extract recipe image URL"""
        selectors = [
            'img[class*="svelte"]',
            'img[class*="full"]',
            'img[src*="eatthismuch"]',
            'img[loading="eager"]'
        ]
        
        for selector in selectors:
            images = soup.select(selector)
            for img in images:
                src = img.get('src')
                if src and 'eatthismuch' in src:
                    if src.startswith('//'):
                        return 'https:' + src
                    elif src.startswith('/'):
                        return urljoin(base_url, src)
                    return src
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract comprehensive recipe description"""
        descriptions = []
        
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            content = meta_desc.get('content', '').strip()
            if content:
                descriptions.append(content)
        
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc:
            content = og_desc.get('content', '').strip()
            if content and content not in descriptions:
                descriptions.append(content)
        
        all_text = soup.get_text()
        lines = all_text.split('\n')
        
        for line in lines[:20]:
            line = line.strip()
            if ('serving' in line.lower() and 'contains' in line.lower() and 'calories' in line.lower()) or \
               ('macronutrient' in line.lower() and 'breakdown' in line.lower()):
                if line not in descriptions:
                    descriptions.append(line)
        
        paragraphs = soup.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 50 and any(word in text.lower() for word in ['serving', 'calories', 'contains', 'macronutrient', 'breakdown']):
                if text not in descriptions:
                    descriptions.append(text)
        
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'description' in data:
                    desc = data['description'].strip()
                    if desc and desc not in descriptions:
                        descriptions.append(desc)
            except:
                continue
        
        if descriptions:
            return max(descriptions, key=len)
        
        return None
    
    def _extract_meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract meta description"""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            return meta_desc.get('content', '').strip()
        return None
    
    def _extract_og_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract OpenGraph description"""
        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc:
            return og_desc.get('content', '').strip()
        return None
    
    def _extract_servings(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract serving count"""
        dd_elements = soup.find_all('dd')
        for dd in dd_elements:
            text = dd.get_text(strip=True).lower()
            if 'serving' in text:
                match = re.search(r'(\d+)', text)
                if match:
                    return int(match.group(1))
        
        all_text = soup.get_text()
        patterns = [
            r'(\d+)\s*serving[s]?',
            r'serves\s*(\d+)',
            r'makes\s*(\d+)\s*serving[s]?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        return None
    
    def _extract_times(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract all time information"""
        times = {}
        
        dt_elements = soup.find_all('dt')
        for dt in dt_elements:
            dt_text = dt.get_text(strip=True).lower()
            dd = dt.find_next_sibling('dd')
            
            if dd:
                dd_text = dd.get_text(strip=True)
                if 'prep' in dt_text:
                    times['prep_time'] = dd_text
                elif 'cook' in dt_text:
                    times['cook_time'] = dd_text
                elif 'total' in dt_text:
                    times['total_time'] = dd_text
                elif 'time' in dt_text:
                    times[dt_text.replace(' ', '_')] = dd_text
        
        all_text = soup.get_text()
        time_patterns = {
            'prep_time': r'prep(?:aration)?\s*time[:\s]*([^\n]+?)(?:\n|$)',
            'cook_time': r'cook(?:ing)?\s*time[:\s]*([^\n]+?)(?:\n|$)',
            'total_time': r'total\s*time[:\s]*([^\n]+?)(?:\n|$)'
        }
        
        for time_type, pattern in time_patterns.items():
            if time_type not in times:
                match = re.search(pattern, all_text, re.IGNORECASE)
                if match:
                    times[time_type] = match.group(1).strip()
        
        return times
    
    def _extract_nutrition(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract comprehensive nutrition data"""
        nutrition = {}
        
        all_text = soup.get_text()
        lines = all_text.split('\n')
        
        in_nutrition = False
        for line in lines:
            line = line.strip()
            
            if 'Nutrition Facts' in line or 'nutrition facts' in line:
                in_nutrition = True
                continue
            
            if in_nutrition and line and any(section in line for section in ['Vitamins', 'Sugars', 'Fats', 'Fatty Acids', 'Amino Acids']):
                break
            
            if in_nutrition and line and '|' in line:
                parts = [part.strip() for part in line.split('|')]
                if len(parts) >= 2:
                    nutrient = re.sub(r'[^\w\s]', '', parts[0].lower()).strip()
                    value = parts[1]
                    
                    if nutrient and value and value != 'Value':
                        nutrition[nutrient] = value
        
        nutrition_sections = soup.find_all(['section', 'div'], class_=lambda x: x and 'nutrition' in x.lower())
        for section in nutrition_sections:
            table = section.find('table')
            if table:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        nutrient = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                        
                        nutrient = re.sub(r'[^\w\s]', '', nutrient)
                        if nutrient and value and nutrient != 'nutrient':
                            nutrition[nutrient] = value
        
        patterns = {
            'calories': r'(\d+(?:\.\d+)?)\s*(?:cal|kcal|calories)',
            'protein': r'(\d+(?:\.\d+)?)\s*g?\s*protein',
            'carbs': r'(\d+(?:\.\d+)?)\s*g?\s*carb',
            'fat': r'(\d+(?:\.\d+)?)\s*g?\s*fat',
            'fiber': r'(\d+(?:\.\d+)?)\s*g?\s*fiber',
            'sugar': r'(\d+(?:\.\d+)?)\s*g?\s*sugar',
            'sodium': r'(\d+(?:\.\d+)?)\s*mg?\s*sodium',
            'cholesterol': r'(\d+(?:\.\d+)?)\s*mg?\s*cholesterol'
        }
        
        for nutrient, pattern in patterns.items():
            if nutrient not in nutrition:
                match = re.search(pattern, all_text, re.IGNORECASE)
                if match:
                    nutrition[nutrient] = match.group(1)
        
        return nutrition
    
    def _extract_ingredients(self, soup: BeautifulSoup) -> List[str]:
        """Extract ingredients"""
        ingredients = []
        
        headings = soup.find_all('h2')
        for heading in headings:
            if 'ingredients' in heading.get_text(strip=True).lower():
                ingredients_section = heading.find_next_sibling()
                if ingredients_section:
                    ul_elements = ingredients_section.find_all('ul', recursive=True)
                    for ul in ul_elements:
                        li_elements = ul.find_all('li')
                        temp_ingredients = []
                        for li in li_elements:
                            ingredient_text = li.get_text(strip=True)
                            if ingredient_text and len(ingredient_text) > 1:
                                temp_ingredients.append(ingredient_text)
                        
                        if temp_ingredients:
                            ingredients.extend(temp_ingredients)
                            break
                break
        
        if not ingredients:
            svelte_lists = soup.find_all('ul', class_=lambda x: x and 'svelte' in x)
            for ul in svelte_lists:
                li_elements = ul.find_all('li')
                temp_ingredients = []
                for li in li_elements:
                    text = li.get_text(strip=True)
                    if text and len(text) > 3 and not text.isdigit():
                        temp_ingredients.append(text)
                
                if len(temp_ingredients) > 1:
                    ingredients = temp_ingredients
                    break
        
        if not ingredients:
            all_lists = soup.find_all(['ul', 'ol'])
            for ul in all_lists:
                li_elements = ul.find_all('li')
                temp_ingredients = []
                
                for li in li_elements:
                    text = li.get_text(strip=True)
                    if (text and len(text) > 3 and len(text) < 200 and 
                        not text.isdigit() and 
                        (any(word in text.lower() for word in ['cup', 'tbsp', 'tsp', 'oz', 'lb', 'gram', 'kg', 'ml', 'liter']) or
                        any(food in text.lower() for food in ['chicken', 'beef', 'egg', 'milk', 'flour', 'sugar', 'salt', 'pepper', 'oil']))):
                        temp_ingredients.append(text)
                
                if len(temp_ingredients) >= 2:
                    ingredients = temp_ingredients
                    break
        
        return ingredients
    
    def _extract_instructions(self, soup: BeautifulSoup) -> List[str]:
        """Extract cooking instructions comprehensively"""
        instructions = []
        
        all_text = soup.get_text()
        if any(word in all_text for word in ['Directions', 'Instructions']):
            lines = all_text.split('\n')
            in_directions = False
            
            for line in lines:
                line = line.strip()
                
                if line.lower() in ['directions', 'instructions', 'method', 'steps']:
                    in_directions = True
                    continue
                
                if in_directions and line and any(section in line for section in ['Nutrition Facts', 'Ingredients']):
                    break
                
                if in_directions and line and len(line) > 15:
                    if not line.endswith(':') and not line.isupper():
                        instructions.append(line)
        
        if not instructions:
            headings = soup.find_all(['h1', 'h2', 'h3', 'h4'])
            for heading in headings:
                heading_text = heading.get_text(strip=True).lower()
                if any(word in heading_text for word in ['instructions', 'directions', 'method', 'steps', 'preparation']):
                    current = heading.next_sibling
                    temp_instructions = []
                    
                    while current:
                        if hasattr(current, 'name') and current.name in ['h1', 'h2', 'h3', 'h4']:
                            break
                        
                        if hasattr(current, 'get_text'):
                            text = current.get_text(strip=True)
                            if text and len(text) > 10:
                                if current.name in ['li', 'p', 'div']:
                                    temp_instructions.append(text)
                        
                        current = current.next_sibling
                    
                    if temp_instructions:
                        instructions = temp_instructions
                        break
        
        if not instructions:
            lists = soup.find_all(['ul', 'ol'])
            for list_elem in lists:
                li_elements = list_elem.find_all('li')
                temp_instructions = []
                
                for li in li_elements:
                    text = li.get_text(strip=True)
                    if (text and len(text) > 20 and 
                        any(word in text.lower() for word in ['place', 'add', 'cook', 'heat', 'mix', 'stir', 'turn', 'bring', 'let', 'transfer', 'remove', 'serve'])):
                        temp_instructions.append(text)
                
                if len(temp_instructions) >= 2:
                    instructions = temp_instructions
                    break
        
        cleaned_instructions = []
        for instruction in instructions:
            cleaned = re.sub(r'^[-•·*\d+\.\)]\s*', '', instruction.strip())
            if cleaned:
                cleaned_instructions.append(cleaned)
        
        return cleaned_instructions
    
    def _extract_tags(self, soup: BeautifulSoup) -> List[str]:
        """Extract recipe tags"""
        tags = []
        
        links = soup.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            if (any(keyword in href.lower() for keyword in ['tag', 'category', 'cuisine', 'diet']) and 
                text and len(text) < 30):
                tags.append(text)
        
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords:
            keywords = meta_keywords.get('content', '').split(',')
            tags.extend([k.strip() for k in keywords if k.strip()])
        
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if 'recipeCategory' in data:
                        if isinstance(data['recipeCategory'], list):
                            tags.extend(data['recipeCategory'])
                        else:
                            tags.append(data['recipeCategory'])
                    
                    if 'recipeCuisine' in data:
                        if isinstance(data['recipeCuisine'], list):
                            tags.extend(data['recipeCuisine'])
                        else:
                            tags.append(data['recipeCuisine'])
            except:
                continue
        
        return list(set(tags))
    
    def _extract_recipe_info(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract additional recipe information"""
        info = {}
        
        dl_elements = soup.find_all('dl')
        
        for dl in dl_elements:
            dt_elements = dl.find_all('dt')
            
            for dt in dt_elements:
                dt_text = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling('dd')
                
                if dd:
                    dd_text = dd.get_text(strip=True)
                    if dt_text and dd_text:
                        info[dt_text] = dd_text
        
        section_elements = soup.find_all(['section', 'div'], class_=lambda x: x and 'info' in x.lower())
        for section in section_elements:
            text = section.get_text()
            lines = text.split('\n')
            for line in lines:
                if ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value = parts[1].strip()
                        if key and value and len(key) < 50 and len(value) < 200:
                            info[key] = value
        
        return info
    
    def scrape_multiple_recipes(self, base_url: str, max_recipes: int = 50, max_pages: int = 10, delay: int = 2) -> Tuple[int, int]:
        """Scrape multiple recipes with pagination"""
        logger.info(f"🚀 Starting scrape: {max_recipes} recipes from up to {max_pages} pages")
        
        recipe_links = self.get_recipe_links_with_pagination(base_url, max_recipes, max_pages)
        successful = failed = 0
        
        for i, url in enumerate(recipe_links, 1):
            try:
                logger.info(f"\n{'='*70}")
                logger.info(f"📖 Scraping {i}/{len(recipe_links)}: {url}")
                logger.info(f"{'='*70}")
                
                recipe_data = self.scrape_recipe(url)
                
                if recipe_data and recipe_data.get('title'):
                    if self.db.save_eatthismuch_recipe(recipe_data):
                        successful += 1
                        logger.info(f"✅ SUCCESS: Recipe saved")
                    else:
                        failed += 1
                        logger.error(f"❌ FAILED: Database save error")
                else:
                    failed += 1
                    logger.error(f"❌ FAILED: Could not extract recipe data")
                
                time.sleep(delay)
                
            except Exception as e:
                logger.error(f"❌ Error processing {url}: {e}")
                failed += 1
        
        logger.info(f"\n{'='*70}")
        logger.info(f"🏁 Scraping completed - Success: {successful}, Failed: {failed}")
        logger.info(f"{'='*70}")
        return successful, failed


# Configuration
SCRAPING_CONFIG = {
    'max_recipes': 100,
    'max_pages': 20,
    'delay_seconds': 2,
    'base_url': 'https://www.eatthismuch.com/food/browse?type=recipe'
}


def main():
    """Main execution function"""
    print("\n" + "="*80)
    print("EATTHISMUCH RECIPE SCRAPER - CONSOLIDATED DATABASE VERSION")
    print("="*80)
    print("\n✨ Features:")
    print("  ✓ Uses consolidated database schema (NO redundant tables)")
    print("  ✓ Automatic total_time calculation (prep_time + cook_time)")
    print("  ✓ Pagination support (follows 'More Results' automatically)")
    print("  ✓ Comprehensive data extraction")
    print("  ✓ Enhanced logging and debugging")
    print("\n" + "="*80)
    
    try:
        # Initialize consolidated database
        logger.info("📊 Initializing consolidated database connection...")
        db = UnifiedRecipeDatabase(DB_CONFIG)
        db.connect()
        logger.info("✅ Database connected successfully")
        
        # Show current stats
        stats = db.get_database_stats()
        print("\n📈 Current Database Statistics:")
        for key, value in stats.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    print(f"  {sub_key}: {sub_value}")
            else:
                print(f"  {key}: {value}")
        
        print(f"\n⚙️  Configuration:")
        print(f"  Max recipes: {SCRAPING_CONFIG['max_recipes']}")
        print(f"  Max pages: {SCRAPING_CONFIG['max_pages']}")
        print(f"  Delay: {SCRAPING_CONFIG['delay_seconds']}s")
        print(f"  Base URL: {SCRAPING_CONFIG['base_url']}")
        
        response = input(f"\n🤔 Start scraping? (y/n): ").lower()
        if response != 'y':
            print("❌ Scraping cancelled.")
            db.close()
            return
        
        # Start scraping
        print(f"\n🏃 Starting scrape...\n")
        scraper = EatThisMuchScraperConsolidated(db)
        successful, failed = scraper.scrape_multiple_recipes(
            base_url=SCRAPING_CONFIG['base_url'],
            max_recipes=SCRAPING_CONFIG['max_recipes'],
            max_pages=SCRAPING_CONFIG['max_pages'],
            delay=SCRAPING_CONFIG['delay_seconds']
        )
        
        # Show final results
        print("\n" + "="*80)
        print("📊 FINAL RESULTS")
        print("="*80)
        print(f"✅ Successfully scraped: {successful} recipes")
        print(f"❌ Failed: {failed} recipes")
        
        if successful + failed > 0:
            success_rate = (successful / (successful + failed) * 100)
            print(f"📈 Success rate: {success_rate:.1f}%")
        
        # Show updated database stats
        stats = db.get_database_stats()
        print("\n📊 Final Database Statistics:")
        for key, value in stats.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    print(f"  {sub_key}: {sub_value}")
            else:
                print(f"  {key}: {value}")
        
        print("\n" + "="*80)
        print("✅ SCRAPING COMPLETE!")
        print("="*80)
        print("\n💡 Tips:")
        print("  • Check the logs above for detailed information")
        print("  • Total time is automatically calculated from prep + cook time")
        print("  • If ingredients/instructions are missing, the website structure may have changed")
        print("  • All data is stored in the consolidated database schema")
        print("  • Compatible with Edamam scraper data")
        
    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        print("\n🔧 Troubleshooting tips:")
        print("  1. Ensure PostgreSQL is running")
        print("  2. Check database credentials in consolidated_db_schema.py")
        print("  3. Verify 'recipes_db' database exists")
        print("  4. Check network connection")
        print("  5. Ensure EatThisMuch.com is accessible")
    finally:
        if 'db' in locals():
            db.close()
            logger.info("Database connection closed")


if __name__ == "__main__":
    main()
    input("\n⏸️  Press Enter to exit...")