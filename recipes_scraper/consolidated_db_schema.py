#!/usr/bin/env python3
"""
Unified Recipe Database Schema - COMPLETE VERSION WITH DECIMAL FIX
- Spoonacular recipes table
- Edamam recipes table  
- Common consolidated table
- Auto-sync triggers (FIXED for decimal percentages)
- NOW INCLUDES: save_eatthismuch_recipe() method
"""

import psycopg2
import logging
import re
import json
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UnifiedRecipeDatabase:
    """Unified database with source-specific and common tables"""
    
    DISALLOWED_CHARS = r'["\*]'
    
    def __init__(self, db_config):
        self.db_config = db_config
        self.connection = None
    
    def _validate_text(self, text, field_name="field"):
        """Validate and clean text by removing disallowed characters"""
        if not isinstance(text, str):
            return text
        
        if re.search(self.DISALLOWED_CHARS, text):
            logger.warning(f"Removing disallowed characters from {field_name}")
            cleaned = re.sub(self.DISALLOWED_CHARS, '', text)
            return cleaned.strip()
        
        return text
    
    def _validate_list_items(self, items, field_name="items"):
        """Validate and clean list items"""
        if not isinstance(items, list):
            return items
        
        cleaned_items = []
        for item in items:
            if isinstance(item, str):
                cleaned = self._validate_text(item, f"{field_name} item")
                if cleaned:
                    cleaned_items.append(cleaned)
            else:
                cleaned_items.append(item)
        
        return cleaned_items
    
    def connect(self):
        """Connect to PostgreSQL database"""
        try:
            self.connection = psycopg2.connect(**self.db_config)
            logger.info("✅ Connected to database")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise
    
    def create_schema(self):
        """Create unified database schema with all tables"""
        try:
            cursor = self.connection.cursor()
            
            logger.info("Creating unified database schema...")
            
            # Drop existing tables
            cursor.execute("DROP TABLE IF EXISTS recipe_tags CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS recipe_directions CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS recipe_nutrition CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS recipe_ingredients CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS recipes CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS spoonacular_recipes CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS edamam_recipes CASCADE;")
            
            # ==================== SPOONACULAR TABLE ====================
            logger.info("Creating Spoonacular recipes table...")
            cursor.execute("""
                CREATE TABLE spoonacular_recipes (
                    id SERIAL PRIMARY KEY,
                    spoonacular_id INTEGER UNIQUE NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    image_url TEXT,
                    image_type VARCHAR(50),
                    source_url TEXT,
                    summary TEXT,
                    cuisines JSONB,
                    dish_types JSONB,
                    servings INTEGER,
                    ready_in_minutes INTEGER,
                    prep_minutes INTEGER,
                    cook_minutes INTEGER,
                    aggregated_likes INTEGER,
                    health_score FLOAT,
                    diets JSONB,
                    source_name VARCHAR(200),
                    
                    ingredients JSONB,
                    directions JSONB,
                    nutrition JSONB,
                    
                    is_vegetarian BOOLEAN,
                    is_vegan BOOLEAN,
                    is_gluten_free BOOLEAN,
                    is_dairy_free BOOLEAN,
                    is_paleo BOOLEAN,
                    is_whole30 BOOLEAN,
                    is_very_healthy BOOLEAN,
                    is_cheap BOOLEAN,
                    is_very_popular BOOLEAN,
                    
                    ai_analysis TEXT,
                    ai_generated_directions JSONB,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX idx_spoon_id ON spoonacular_recipes(spoonacular_id);
                CREATE INDEX idx_spoon_title ON spoonacular_recipes(title);
            """)
            
            # ==================== EDAMAM TABLE ====================
            logger.info("Creating Edamam recipes table...")
            cursor.execute("""
                CREATE TABLE edamam_recipes (
                    id SERIAL PRIMARY KEY,
                    recipe_id VARCHAR(255) UNIQUE NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    image_url TEXT,
                    source_url TEXT UNIQUE NOT NULL,
                    source_name VARCHAR(255),
                    servings INTEGER,
                    calories_per_serving INTEGER,
                    
                    prep_time VARCHAR(100),
                    cook_time VARCHAR(100),
                    total_time VARCHAR(100),
                    
                    ingredients JSONB,
                    directions JSONB,
                    nutrition JSONB,
                    
                    diet_labels JSONB,
                    health_labels JSONB,
                    cautions JSONB,
                    
                    ai_analysis TEXT,
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX idx_edamam_recipe_id ON edamam_recipes(recipe_id);
                CREATE INDEX idx_edamam_title ON edamam_recipes(title);
                CREATE INDEX idx_edamam_url ON edamam_recipes(source_url);
            """)
            
            # ==================== COMMON/CONSOLIDATED TABLE ====================
            logger.info("Creating common recipes table...")
            cursor.execute("""
                CREATE TABLE recipes (
                    id SERIAL PRIMARY KEY,
                    
                    -- Basic info
                    title VARCHAR(500) NOT NULL,
                    url TEXT NOT NULL,
                    image_url TEXT,
                    servings INTEGER,
                    
                    -- Source tracking
                    source VARCHAR(50) NOT NULL CHECK (source IN ('spoonacular', 'edamam', 'eatthismuch')),
                    source_id VARCHAR(255),
                    source_name VARCHAR(255),
                    source_url TEXT,
                    
                    -- Time fields
                    prep_time VARCHAR(100),
                    cook_time VARCHAR(100),
                    total_time VARCHAR(100),
                    ready_in_minutes INTEGER,
                    
                    -- Description and analysis
                    description TEXT,
                    summary TEXT,
                    ai_analysis TEXT,
                    
                    -- Nutritional info
                    calories_per_serving INTEGER,
                    health_score FLOAT,
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    
                    CONSTRAINT unique_recipe_source UNIQUE (source, source_id)
                );
            """)
            
            cursor.execute("""
                CREATE INDEX idx_recipes_source ON recipes(source);
                CREATE INDEX idx_recipes_source_id ON recipes(source_id);
                CREATE INDEX idx_recipes_url ON recipes(url);
                CREATE INDEX idx_recipes_title ON recipes(title);
            """)
            
            # ==================== CHILD TABLES ====================
            logger.info("Creating child tables...")
            
            # Ingredients
            cursor.execute("""
                CREATE TABLE recipe_ingredients (
                    id SERIAL PRIMARY KEY,
                    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
                    ingredient_text TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX idx_recipe_ingredients_recipe_id ON recipe_ingredients(recipe_id);
            """)
            
            # Directions
            cursor.execute("""
                CREATE TABLE recipe_directions (
                    id SERIAL PRIMARY KEY,
                    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
                    direction_text TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX idx_recipe_directions_recipe_id ON recipe_directions(recipe_id);
            """)
            
            # Nutrition - FIXED: Changed daily_value_percent to DECIMAL
            cursor.execute("""
                CREATE TABLE recipe_nutrition (
                    id SERIAL PRIMARY KEY,
                    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
                    nutrient_name VARCHAR(100) NOT NULL,
                    
                    -- Generic format
                    nutrient_value VARCHAR(50),
                    
                    -- Detailed format
                    amount DECIMAL(10, 2),
                    unit VARCHAR(20),
                    daily_value_percent DECIMAL(10, 2),
                    
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(recipe_id, nutrient_name)
                );
                CREATE INDEX idx_recipe_nutrition_recipe_id ON recipe_nutrition(recipe_id);
            """)
            
            # Tags
            cursor.execute("""
                CREATE TABLE recipe_tags (
                    id SERIAL PRIMARY KEY,
                    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
                    tag_type VARCHAR(20) CHECK (tag_type IN ('general', 'diet', 'health', 'cuisine', 'dish_type')),
                    tag_name VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX idx_recipe_tags_recipe_id ON recipe_tags(recipe_id);
                CREATE INDEX idx_recipe_tags_type ON recipe_tags(tag_type);
            """)
            
            # ==================== TRIGGERS ====================
            logger.info("Creating sync triggers...")
            
            # Trigger function to sync Spoonacular to common table - FIXED: DECIMAL cast
            cursor.execute("""
                CREATE OR REPLACE FUNCTION sync_spoonacular_to_common()
                RETURNS TRIGGER AS $$
                DECLARE
                    common_recipe_id INTEGER;
                    ingredient_item JSONB;
                    direction_item JSONB;
                    nutrition_item JSONB;
                    cuisine_item TEXT;
                    dish_type_item TEXT;
                    diet_item TEXT;
                BEGIN
                    -- Insert or update main recipe
                    INSERT INTO recipes (
                        title, url, image_url, servings, source, source_id,
                        source_name, source_url, ready_in_minutes,
                        summary, ai_analysis, health_score
                    )
                    VALUES (
                        NEW.title,
                        COALESCE(NEW.source_url, 'https://spoonacular.com/recipe/' || NEW.spoonacular_id),
                        NEW.image_url,
                        NEW.servings,
                        'spoonacular',
                        NEW.spoonacular_id::TEXT,
                        NEW.source_name,
                        NEW.source_url,
                        NEW.ready_in_minutes,
                        NEW.summary,
                        NEW.ai_analysis,
                        NEW.health_score
                    )
                    ON CONFLICT (source, source_id) 
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        url = EXCLUDED.url,
                        image_url = EXCLUDED.image_url,
                        servings = EXCLUDED.servings,
                        source_name = EXCLUDED.source_name,
                        source_url = EXCLUDED.source_url,
                        ready_in_minutes = EXCLUDED.ready_in_minutes,
                        summary = EXCLUDED.summary,
                        ai_analysis = EXCLUDED.ai_analysis,
                        health_score = EXCLUDED.health_score,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id INTO common_recipe_id;
                    
                    -- Clear existing child data
                    DELETE FROM recipe_ingredients WHERE recipe_id = common_recipe_id;
                    DELETE FROM recipe_directions WHERE recipe_id = common_recipe_id;
                    DELETE FROM recipe_nutrition WHERE recipe_id = common_recipe_id;
                    DELETE FROM recipe_tags WHERE recipe_id = common_recipe_id;
                    
                    -- Sync ingredients from JSONB
                    IF NEW.ingredients IS NOT NULL THEN
                        FOR ingredient_item IN SELECT * FROM jsonb_array_elements(NEW.ingredients)
                        LOOP
                            INSERT INTO recipe_ingredients (recipe_id, ingredient_text, order_index)
                            VALUES (
                                common_recipe_id,
                                COALESCE(ingredient_item->>'original', ingredient_item->>'name', ''),
                                COALESCE((ingredient_item->>'id')::INTEGER, 0)
                            );
                        END LOOP;
                    END IF;
                    
                    -- Sync directions from JSONB
                    IF NEW.directions IS NOT NULL THEN
                        FOR direction_item IN SELECT * FROM jsonb_array_elements(NEW.directions)
                        LOOP
                            INSERT INTO recipe_directions (recipe_id, direction_text, step_number)
                            VALUES (
                                common_recipe_id,
                                direction_item->>'instruction',
                                COALESCE((direction_item->>'step_number')::INTEGER, 0)
                            );
                        END LOOP;
                    END IF;
                    
                    -- Sync nutrition from JSONB - FIXED: Cast to DECIMAL instead of INTEGER
                    IF NEW.nutrition IS NOT NULL THEN
                        FOR nutrition_item IN SELECT * FROM jsonb_array_elements(NEW.nutrition)
                        LOOP
                            INSERT INTO recipe_nutrition (recipe_id, nutrient_name, amount, unit, daily_value_percent)
                            VALUES (
                                common_recipe_id,
                                nutrition_item->>'name',
                                (nutrition_item->>'amount')::DECIMAL,
                                nutrition_item->>'unit',
                                (nutrition_item->>'percentOfDailyNeeds')::DECIMAL
                            )
                            ON CONFLICT (recipe_id, nutrient_name) DO NOTHING;
                        END LOOP;
                    END IF;
                    
                    -- Sync cuisines as tags
                    IF NEW.cuisines IS NOT NULL THEN
                        FOR cuisine_item IN SELECT jsonb_array_elements_text(NEW.cuisines)
                        LOOP
                            INSERT INTO recipe_tags (recipe_id, tag_type, tag_name)
                            VALUES (common_recipe_id, 'cuisine', cuisine_item);
                        END LOOP;
                    END IF;
                    
                    -- Sync dish types as tags
                    IF NEW.dish_types IS NOT NULL THEN
                        FOR dish_type_item IN SELECT jsonb_array_elements_text(NEW.dish_types)
                        LOOP
                            INSERT INTO recipe_tags (recipe_id, tag_type, tag_name)
                            VALUES (common_recipe_id, 'dish_type', dish_type_item);
                        END LOOP;
                    END IF;
                    
                    -- Sync diets as tags
                    IF NEW.diets IS NOT NULL THEN
                        FOR diet_item IN SELECT jsonb_array_elements_text(NEW.diets)
                        LOOP
                            INSERT INTO recipe_tags (recipe_id, tag_type, tag_name)
                            VALUES (common_recipe_id, 'diet', diet_item);
                        END LOOP;
                    END IF;
                    
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                
                CREATE TRIGGER trigger_sync_spoonacular
                AFTER INSERT OR UPDATE ON spoonacular_recipes
                FOR EACH ROW
                EXECUTE FUNCTION sync_spoonacular_to_common();
            """)
            
            # Trigger function to sync Edamam to common table - FIXED: DECIMAL cast
            cursor.execute("""
                CREATE OR REPLACE FUNCTION sync_edamam_to_common()
                RETURNS TRIGGER AS $$
                DECLARE
                    common_recipe_id INTEGER;
                    ingredient_item TEXT;
                    direction_item TEXT;
                    nutrition_key TEXT;
                    nutrition_value JSONB;
                    diet_label TEXT;
                    health_label TEXT;
                BEGIN
                    -- Insert or update main recipe
                    INSERT INTO recipes (
                        title, url, image_url, servings, source, source_id,
                        source_name, source_url, prep_time, cook_time, total_time,
                        ai_analysis, calories_per_serving
                    )
                    VALUES (
                        NEW.title,
                        NEW.source_url,
                        NEW.image_url,
                        NEW.servings,
                        'edamam',
                        NEW.recipe_id,
                        NEW.source_name,
                        NEW.source_url,
                        NEW.prep_time,
                        NEW.cook_time,
                        NEW.total_time,
                        NEW.ai_analysis,
                        NEW.calories_per_serving
                    )
                    ON CONFLICT (source, source_id) 
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        url = EXCLUDED.url,
                        image_url = EXCLUDED.image_url,
                        servings = EXCLUDED.servings,
                        source_name = EXCLUDED.source_name,
                        source_url = EXCLUDED.source_url,
                        prep_time = EXCLUDED.prep_time,
                        cook_time = EXCLUDED.cook_time,
                        total_time = EXCLUDED.total_time,
                        ai_analysis = EXCLUDED.ai_analysis,
                        calories_per_serving = EXCLUDED.calories_per_serving,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id INTO common_recipe_id;
                    
                    -- Clear existing child data
                    DELETE FROM recipe_ingredients WHERE recipe_id = common_recipe_id;
                    DELETE FROM recipe_directions WHERE recipe_id = common_recipe_id;
                    DELETE FROM recipe_nutrition WHERE recipe_id = common_recipe_id;
                    DELETE FROM recipe_tags WHERE recipe_id = common_recipe_id;
                    
                    -- Sync ingredients from JSONB array
                    IF NEW.ingredients IS NOT NULL THEN
                        FOR ingredient_item IN SELECT jsonb_array_elements_text(NEW.ingredients)
                        LOOP
                            INSERT INTO recipe_ingredients (recipe_id, ingredient_text, order_index)
                            VALUES (common_recipe_id, ingredient_item, 0);
                        END LOOP;
                    END IF;
                    
                    -- Sync directions from JSONB array
                    IF NEW.directions IS NOT NULL THEN
                        FOR direction_item IN SELECT jsonb_array_elements_text(NEW.directions)
                        LOOP
                            INSERT INTO recipe_directions (recipe_id, direction_text, step_number)
                            VALUES (common_recipe_id, direction_item, 0);
                        END LOOP;
                    END IF;
                    
                    -- Sync nutrition from JSONB object - FIXED: DECIMAL cast
                    IF NEW.nutrition IS NOT NULL THEN
                        FOR nutrition_key, nutrition_value IN SELECT * FROM jsonb_each(NEW.nutrition)
                        LOOP
                            INSERT INTO recipe_nutrition (recipe_id, nutrient_name, amount, unit, daily_value_percent)
                            VALUES (
                                common_recipe_id,
                                nutrition_key,
                                (nutrition_value->>'amount')::DECIMAL,
                                nutrition_value->>'unit',
                                (nutrition_value->>'daily_value_percent')::DECIMAL
                            )
                            ON CONFLICT (recipe_id, nutrient_name) DO NOTHING;
                        END LOOP;
                    END IF;
                    
                    -- Sync diet labels
                    IF NEW.diet_labels IS NOT NULL THEN
                        FOR diet_label IN SELECT jsonb_array_elements_text(NEW.diet_labels)
                        LOOP
                            INSERT INTO recipe_tags (recipe_id, tag_type, tag_name)
                            VALUES (common_recipe_id, 'diet', diet_label);
                        END LOOP;
                    END IF;
                    
                    -- Sync health labels
                    IF NEW.health_labels IS NOT NULL THEN
                        FOR health_label IN SELECT jsonb_array_elements_text(NEW.health_labels)
                        LOOP
                            INSERT INTO recipe_tags (recipe_id, tag_type, tag_name)
                            VALUES (common_recipe_id, 'health', health_label);
                        END LOOP;
                    END IF;
                    
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                
                CREATE TRIGGER trigger_sync_edamam
                AFTER INSERT OR UPDATE ON edamam_recipes
                FOR EACH ROW
                EXECUTE FUNCTION sync_edamam_to_common();
            """)
            
            self.connection.commit()
            logger.info("✅ Database schema created successfully")
            self._log_schema_summary()
            
        except Exception as e:
            logger.error(f"Error creating schema: {e}")
            self.connection.rollback()
            raise
    
    def _log_schema_summary(self):
        """Log schema summary"""
        logger.info("\n" + "="*80)
        logger.info("UNIFIED RECIPE DATABASE SCHEMA")
        logger.info("="*80)
        logger.info("\n📋 SOURCE TABLES:")
        logger.info("  1. spoonacular_recipes: Spoonacular data with JSONB fields")
        logger.info("  2. edamam_recipes: Edamam data with JSONB fields")
        logger.info("\n📋 COMMON/CONSOLIDATED TABLES:")
        logger.info("  1. recipes: Unified recipe metadata")
        logger.info("  2. recipe_ingredients: All ingredients")
        logger.info("  3. recipe_directions: Cooking steps")
        logger.info("  4. recipe_nutrition: Nutrition data (DECIMAL percentages)")
        logger.info("  5. recipe_tags: Diet, health, cuisine, dish type tags")
        logger.info("\n🔄 AUTO-SYNC:")
        logger.info("  ✓ Triggers automatically sync source tables to common tables")
        logger.info("  ✓ Insert/Update on source tables updates common tables")
        logger.info("\n✅ INPUT VALIDATION:")
        logger.info("  ✓ Disallowed characters removed: \" and *")
        logger.info("\n🔧 BUG FIXES:")
        logger.info("  ✓ daily_value_percent now accepts DECIMAL values (not just INTEGER)")
        logger.info("="*80 + "\n")
    
    def get_database_stats(self):
        """Get database statistics"""
        try:
            cursor = self.connection.cursor()
            stats = {}
            
            # Count by source in common table
            cursor.execute("SELECT source, COUNT(*) FROM recipes GROUP BY source")
            result = cursor.fetchall()
            if result:
                stats['recipes_by_source'] = dict(result)
            
            # Count all tables
            tables = {
                'spoonacular_recipes': 'Spoonacular',
                'edamam_recipes': 'Edamam',
                'recipes': 'Common Recipes',
                'recipe_ingredients': 'Ingredients',
                'recipe_directions': 'Directions',
                'recipe_nutrition': 'Nutrition',
                'recipe_tags': 'Tags'
            }
            
            for table, label in tables.items():
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[label] = cursor.fetchone()[0]
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
    
    def save_eatthismuch_recipe(self, recipe_data):
        """
        Save recipe from EatThisMuch scraper directly to consolidated tables.
        This bypasses source-specific tables and goes straight to the common schema.
        """
        try:
            cursor = self.connection.cursor()
            
            # Extract and validate data
            url = recipe_data.get('url', '')
            title = self._validate_text(recipe_data.get('title', 'Unknown Recipe'), "title")
            
            # Generate a unique source_id from the URL
            source_id = hashlib.md5(url.encode()).hexdigest()[:16]
            
            logger.info(f"📝 Saving EatThisMuch recipe: {title}")
            
            # Extract time fields
            times = recipe_data.get('times', {})
            prep_time = times.get('prep_time')
            cook_time = times.get('cook_time')
            total_time = times.get('total_time')
            
            # Extract description
            description = recipe_data.get('description') or recipe_data.get('meta_description') or recipe_data.get('og_description')
            
            # Extract nutrition data
            nutrition = recipe_data.get('nutrition', {})
            calories = nutrition.get('calories') or nutrition.get('Calories')
            
            # Insert into recipes table
            cursor.execute("""
                INSERT INTO recipes (
                    title, url, image_url, servings, source, source_id,
                    source_name, source_url, prep_time, cook_time, total_time,
                    description, calories_per_serving
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, source_id) 
                DO UPDATE SET
                    title = EXCLUDED.title,
                    url = EXCLUDED.url,
                    image_url = EXCLUDED.image_url,
                    servings = EXCLUDED.servings,
                    source_name = EXCLUDED.source_name,
                    source_url = EXCLUDED.source_url,
                    prep_time = EXCLUDED.prep_time,
                    cook_time = EXCLUDED.cook_time,
                    total_time = EXCLUDED.total_time,
                    description = EXCLUDED.description,
                    calories_per_serving = EXCLUDED.calories_per_serving,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id;
            """, (
                title,
                url,
                recipe_data.get('image_url'),
                recipe_data.get('servings'),
                'eatthismuch',
                source_id,
                'EatThisMuch',
                url,
                prep_time,
                cook_time,
                total_time,
                description,
                int(calories) if calories and str(calories).replace('.','').isdigit() else None
            ))
            
            recipe_id = cursor.fetchone()[0]
            
            # Clear existing child data (in case of update)
            cursor.execute("DELETE FROM recipe_ingredients WHERE recipe_id = %s", (recipe_id,))
            cursor.execute("DELETE FROM recipe_directions WHERE recipe_id = %s", (recipe_id,))
            cursor.execute("DELETE FROM recipe_nutrition WHERE recipe_id = %s", (recipe_id,))
            cursor.execute("DELETE FROM recipe_tags WHERE recipe_id = %s", (recipe_id,))
            
            # Insert ingredients
            ingredients = recipe_data.get('ingredients', [])
            if ingredients:
                for idx, ingredient in enumerate(ingredients):
                    ingredient_text = self._validate_text(str(ingredient), "ingredient")
                    if ingredient_text:
                        cursor.execute("""
                            INSERT INTO recipe_ingredients (recipe_id, ingredient_text, order_index)
                            VALUES (%s, %s, %s)
                        """, (recipe_id, ingredient_text, idx))
            
            # Insert instructions/directions
            instructions = recipe_data.get('instructions', [])
            if instructions:
                for idx, instruction in enumerate(instructions, 1):
                    instruction_text = self._validate_text(str(instruction), "instruction")
                    if instruction_text:
                        cursor.execute("""
                            INSERT INTO recipe_directions (recipe_id, direction_text, step_number)
                            VALUES (%s, %s, %s)
                        """, (recipe_id, instruction_text, idx))
            
            # Insert nutrition data
            if nutrition:
                for nutrient_name, nutrient_value in nutrition.items():
                    nutrient_name = self._validate_text(str(nutrient_name), "nutrient_name")
                    if nutrient_name and nutrient_value:
                        cursor.execute("""
                            INSERT INTO recipe_nutrition (recipe_id, nutrient_name, nutrient_value)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (recipe_id, nutrient_name) DO UPDATE 
                            SET nutrient_value = EXCLUDED.nutrient_value
                        """, (recipe_id, nutrient_name, str(nutrient_value)))
            
            # Insert tags
            tags = recipe_data.get('tags', [])
            if tags:
                for tag in tags:
                    tag_text = self._validate_text(str(tag), "tag")
                    if tag_text:
                        cursor.execute("""
                            INSERT INTO recipe_tags (recipe_id, tag_type, tag_name)
                            VALUES (%s, %s, %s)
                        """, (recipe_id, 'general', tag_text))
            
            self.connection.commit()
            
            logger.info(f"✅ EatThisMuch recipe saved (ID: {recipe_id})")
            logger.info(f"   ✓ {len(ingredients)} ingredients")
            logger.info(f"   ✓ {len(instructions)} directions")
            logger.info(f"   ✓ {len(nutrition)} nutrition entries")
            logger.info(f"   ✓ {len(tags)} tags")
            
            return recipe_id
            
        except Exception as e:
            logger.error(f"Error saving EatThisMuch recipe: {e}")
            self.connection.rollback()
            import traceback
            traceback.print_exc()
            return None
    
    def save_edamam_recipe(self, recipe_data):
        """Save recipe from Edamam scraper to edamam_recipes table"""
        try:
            cursor = self.connection.cursor()
            
            # Validate text fields
            title = self._validate_text(recipe_data.get('title', ''), "title")
            source_name = self._validate_text(recipe_data.get('source_name', ''), "source_name") if recipe_data.get('source_name') else None
            ai_analysis = self._validate_text(recipe_data.get('recipe_analysis', ''), "recipe_analysis") if recipe_data.get('recipe_analysis') else None
            
            logger.info(f"📝 Saving Edamam recipe: {title}")
            
            # Prepare JSONB data
            ingredients = self._validate_list_items(recipe_data.get('ingredients', []), "ingredients")
            ingredients_json = json.dumps(ingredients) if ingredients else None
            
            directions = self._validate_list_items(recipe_data.get('directions', []), "directions")
            directions_json = json.dumps(directions) if directions else None
            
            nutrition = recipe_data.get('nutrition', {})
            nutrition_json = json.dumps(nutrition) if nutrition else None
            
            diet_labels = self._validate_list_items(recipe_data.get('diet_labels', []), "diet_labels")
            diet_labels_json = json.dumps(diet_labels) if diet_labels else None
            
            health_labels = self._validate_list_items(recipe_data.get('health_labels', []), "health_labels")
            health_labels_json = json.dumps(health_labels) if health_labels else None
            
            cautions = self._validate_list_items(recipe_data.get('cautions', []), "cautions")
            cautions_json = json.dumps(cautions) if cautions else None
            
            # Insert into edamam_recipes table
            cursor.execute("""
                INSERT INTO edamam_recipes (
                    recipe_id, title, image_url, source_url, source_name,
                    servings, calories_per_serving,
                    prep_time, cook_time, total_time,
                    ingredients, directions, nutrition,
                    diet_labels, health_labels, cautions,
                    ai_analysis
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (recipe_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    image_url = EXCLUDED.image_url,
                    source_name = EXCLUDED.source_name,
                    servings = EXCLUDED.servings,
                    calories_per_serving = EXCLUDED.calories_per_serving,
                    prep_time = EXCLUDED.prep_time,
                    cook_time = EXCLUDED.cook_time,
                    total_time = EXCLUDED.total_time,
                    ingredients = EXCLUDED.ingredients,
                    directions = EXCLUDED.directions,
                    nutrition = EXCLUDED.nutrition,
                    diet_labels = EXCLUDED.diet_labels,
                    health_labels = EXCLUDED.health_labels,
                    cautions = EXCLUDED.cautions,
                    ai_analysis = EXCLUDED.ai_analysis,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id;
            """, (
                recipe_data.get('recipe_id'),
                title,
                recipe_data.get('image_url'),
                recipe_data.get('source_url'),
                source_name,
                recipe_data.get('servings'),
                recipe_data.get('calories_per_serving'),
                recipe_data.get('prep_time'),
                recipe_data.get('cook_time'),
                recipe_data.get('total_time'),
                ingredients_json,
                directions_json,
                nutrition_json,
                diet_labels_json,
                health_labels_json,
                cautions_json,
                ai_analysis
            ))
            
            edamam_id = cursor.fetchone()[0]
            self.connection.commit()
            
            logger.info(f"✅ Edamam recipe saved (ID: {edamam_id})")
            logger.info(f"   ✓ {len(ingredients)} ingredients")
            logger.info(f"   ✓ {len(directions)} directions")
            logger.info(f"   ✓ {len(nutrition)} nutrition entries")
            logger.info(f"   ✓ {len(diet_labels)} diet labels, {len(health_labels)} health labels")
            logger.info(f"   🔄 Auto-syncing to common tables via trigger...")
            
            return edamam_id
            
        except Exception as e:
            logger.error(f"Error saving Edamam recipe: {e}")
            self.connection.rollback()
            import traceback
            traceback.print_exc()
            return None
    
    def save_spoonacular_recipe(self, recipe_data):
        """Save recipe from Spoonacular scraper to spoonacular_recipes table"""
        try:
            cursor = self.connection.cursor()
            
            spoonacular_id = recipe_data.get('spoonacular_id') or recipe_data.get('id')
            
            # Check if already exists
            cursor.execute("SELECT id FROM spoonacular_recipes WHERE spoonacular_id = %s", (spoonacular_id,))
            if cursor.fetchone():
                logger.info(f"Recipe {spoonacular_id} already exists, skipping...")
                return None
            
            logger.info(f"📝 Saving Spoonacular recipe: {recipe_data.get('title', 'Unknown')}")
            
            # Prepare JSONB data
            ingredients_json = json.dumps(recipe_data.get('ingredients', [])) if recipe_data.get('ingredients') else None
            directions_json = json.dumps(recipe_data.get('directions', [])) if recipe_data.get('directions') else None
            nutrition_json = json.dumps(recipe_data.get('nutrition', [])) if recipe_data.get('nutrition') else None
            diets_json = json.dumps(recipe_data.get('diets', [])) if recipe_data.get('diets') else None
            cuisines_json = json.dumps(recipe_data.get('cuisines', [])) if recipe_data.get('cuisines') else None
            dish_types_json = json.dumps(recipe_data.get('dish_types', [])) if recipe_data.get('dish_types') else None
            ai_directions_json = json.dumps(recipe_data.get('ai_generated_directions', [])) if recipe_data.get('ai_generated_directions') else None
            
            # Insert into spoonacular_recipes table
            cursor.execute("""
                INSERT INTO spoonacular_recipes (
                    spoonacular_id, title, image_url, image_type, source_url, summary,
                    cuisines, dish_types, servings, ready_in_minutes, prep_minutes, cook_minutes,
                    aggregated_likes, health_score, diets, source_name,
                    ingredients, directions, nutrition,
                    is_vegetarian, is_vegan, is_gluten_free, is_dairy_free, is_paleo,
                    is_whole30, is_very_healthy, is_cheap, is_very_popular,
                    ai_analysis, ai_generated_directions
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                spoonacular_id,
                recipe_data.get('title'),
                recipe_data.get('image_url') or recipe_data.get('image'),
                recipe_data.get('image_type') or recipe_data.get('imageType'),
                recipe_data.get('source_url') or recipe_data.get('sourceUrl'),
                recipe_data.get('summary'),
                cuisines_json,
                dish_types_json,
                recipe_data.get('servings'),
                recipe_data.get('ready_in_minutes') or recipe_data.get('readyInMinutes'),
                recipe_data.get('prep_minutes') or recipe_data.get('preparationMinutes'),
                recipe_data.get('cook_minutes') or recipe_data.get('cookingMinutes'),
                recipe_data.get('aggregated_likes', 0) or recipe_data.get('aggregateLikes', 0),
                recipe_data.get('health_score', 0) or recipe_data.get('healthScore', 0),
                diets_json,
                recipe_data.get('source_name') or recipe_data.get('sourceName'),
                ingredients_json,
                directions_json,
                nutrition_json,
                recipe_data.get('is_vegetarian', False) or recipe_data.get('vegetarian', False),
                recipe_data.get('is_vegan', False) or recipe_data.get('vegan', False),
                recipe_data.get('is_gluten_free', False) or recipe_data.get('glutenFree', False),
                recipe_data.get('is_dairy_free', False) or recipe_data.get('dairyFree', False),
                recipe_data.get('is_paleo', False) or recipe_data.get('paleo', False),
                recipe_data.get('is_whole30', False) or recipe_data.get('whole30', False),
                recipe_data.get('is_very_healthy', False) or recipe_data.get('veryHealthy', False),
                recipe_data.get('is_cheap', False) or recipe_data.get('cheap', False),
                recipe_data.get('is_very_popular', False) or recipe_data.get('veryPopular', False),
                recipe_data.get('ai_analysis'),
                ai_directions_json
            ))
            
            spoon_id = cursor.fetchone()[0]
            self.connection.commit()
            
            logger.info(f"✅ Spoonacular recipe saved (ID: {spoon_id})")
            logger.info(f"   🔄 Auto-syncing to common tables via trigger...")
            
            return spoon_id
            
        except Exception as e:
            logger.error(f"Error saving Spoonacular recipe: {e}")
            self.connection.rollback()
            import traceback
            traceback.print_exc()
            return None
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")


# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'database': 'recipes_db',
    'user': 'postgres',
    'password': 'Ah72n):(:',
    'port': 5432
}


def initialize_database():
    """Initialize the database schema"""
    db = UnifiedRecipeDatabase(DB_CONFIG)
    try:
        db.connect()
        db.create_schema()
        stats = db.get_database_stats()
        
        logger.info("\n" + "="*80)
        logger.info("DATABASE STATISTICS")
        logger.info("="*80)
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        logger.info("="*80 + "\n")
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("\n" + "="*80)
    print("UNIFIED RECIPE DATABASE SCHEMA - FIXED VERSION")
    print("="*80)
    print("\n📋 FEATURES:")
    print("  • Spoonacular recipes table (with JSONB)")
    print("  • Edamam recipes table (with JSONB)")
    print("  • EatThisMuch support (direct to common tables)")
    print("  • Common/consolidated tables (normalized)")
    print("  • Auto-sync triggers (source → common)")
    print("  • Input validation (removes \" and *)")
    print("\n🔧 BUG FIXES:")
    print("  • daily_value_percent now DECIMAL (was INTEGER)")
    print("  • Handles decimal percentage values like 23.59, 21.8, etc.")
    print("\n🔄 AUTO-SYNC WORKFLOW:")
    print("  1. Insert recipe into spoonacular_recipes or edamam_recipes")
    print("  2. Trigger automatically syncs to common 'recipes' table")
    print("  3. Child tables (ingredients, directions, etc.) auto-populated")
    print("  4. EatThisMuch recipes go directly to common tables")
    print("  5. All data accessible from unified common tables")
    print("\n" + "="*80 + "\n")
    
    initialize_database()
    
    print("\n✅ Database schema created successfully!")
    print("="*80)