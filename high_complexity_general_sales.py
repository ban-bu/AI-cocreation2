import streamlit as st
from PIL import Image, ImageDraw
import requests
from io import BytesIO
import os  # 确保os模块在这里导入
# 添加try-except导入cairosvg，避免因缺少这个库而导致整个应用崩溃
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except ImportError:
    CAIROSVG_AVAILABLE = False
    # 尝试导入备选SVG处理库
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        SVGLIB_AVAILABLE = True
    except ImportError:
        SVGLIB_AVAILABLE = False
        st.warning("SVG处理库未安装，SVG格式转换功能将不可用")
from openai import OpenAI
from streamlit_image_coordinates import streamlit_image_coordinates
import re
import math
# 导入面料纹理模块
from fabric_texture import apply_fabric_texture
import uuid

# API配置信息 - 实际使用时应从主文件传入或使用环境变量
API_KEY = "sk-lNVAREVHjj386FDCd9McOL7k66DZCUkTp6IbV0u9970qqdlg"
BASE_URL = "https://api.deepbricks.ai/v1/"

# GPT-4o-mini API配置
GPT4O_MINI_API_KEY = "sk-lNVAREVHjj386FDCd9McOL7k66DZCUkTp6IbV0u9970qqdlg"
GPT4O_MINI_BASE_URL = "https://api.deepbricks.ai/v1/"

# 从svg_utils导入SVG转换函数
from svg_utils import convert_svg_to_png

def get_ai_design_suggestions(style, color, size, gender, occasion, season, preferences):
    """获取AI设计建议"""
    prompt = f"""You are a professional T-shirt design consultant. Based on the following preferences, provide personalized design suggestions:

Style: {style}
Color: {color}
Size: {size}
Gender: {gender}
Occasion: {occasion}
Season: {season}
Additional Preferences: {preferences}

Please provide:
1. Logo element suggestions (at least 3 different options)
2. Design style recommendations
3. Color scheme suggestions
4. Placement recommendations
5. Additional design elements

Format your response with clear sections and bullet points."""

    try:
        response = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 1000
            }
        )
        
        if response.status_code == 200:
            suggestions = response.json()["choices"][0]["message"]["content"]
            
            # 提取Logo建议
            logo_pattern = r"Logo element suggestions:.*?(?=\n\n|\Z)"
            logo_match = re.search(logo_pattern, suggestions, re.DOTALL)
            if logo_match:
                logo_suggestions = logo_match.group(0).replace("Logo element suggestions:", "").strip()
                logo_suggestions = [s.strip() for s in logo_suggestions.split("\n") if s.strip()]
                
                # 生成第一个Logo
                if logo_suggestions:
                    logo_prompt = f"Create a Logo design: {logo_suggestions[0]}. Requirements: 1. Use a simple design 2. Suitable for printing 3. Background transparent 4. Clear and recognizable pattern"
                    logo_image = generate_vector_image(logo_prompt)
                    
                    if logo_image:
                        # 保存生成的Logo
                        st.session_state.generated_logo = logo_image
                        st.session_state.logo_prompt = logo_suggestions[0]
                        st.session_state.logo_auto_generated = True
                        st.session_state.ai_suggested_logos = logo_suggestions
            
            return suggestions
        else:
            return "Error getting design suggestions"
    except Exception as e:
        return f"Error: {str(e)}"

def generate_vector_image(prompt):
    """Generate an image based on the prompt"""
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    try:
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024",
            quality="standard"
        )
    except Exception as e:
        st.error(f"Error calling API: {e}")
        return None

    if resp and len(resp.data) > 0 and resp.data[0].url:
        image_url = resp.data[0].url
        try:
            image_resp = requests.get(image_url)
            if image_resp.status_code == 200:
                content_type = image_resp.headers.get("Content-Type", "")
                if "svg" in content_type.lower():
                    # 使用集中的SVG处理函数
                    return convert_svg_to_png(image_resp.content)
                else:
                    return Image.open(BytesIO(image_resp.content)).convert("RGBA")
            else:
                st.error(f"Failed to download image, status code: {image_resp.status_code}")
        except Exception as download_err:
            st.error(f"Error requesting image: {download_err}")
    else:
        st.error("Could not get image URL from API response.")
    return None

def draw_selection_box(image, point=None):
    """Calculate position for design placement without drawing visible selection box"""
    # Create a copy to avoid modifying the original image
    img_copy = image.copy()
    
    # Fixed box size (1024 * 0.25)
    box_size = int(1024 * 0.25)
    
    # If no position is specified, place it in the center
    if point is None:
        x1 = (image.width - box_size) // 2
        y1 = (image.height - box_size) // 2
    else:
        x1, y1 = point
        # Ensure the selection box doesn't extend beyond image boundaries
        x1 = max(0, min(x1 - box_size//2, image.width - box_size))
        y1 = max(0, min(y1 - box_size//2, image.height - box_size))
    
    # Return the image without drawing any visible box, just the position
    return img_copy, (x1, y1)

def get_selection_coordinates(point=None, image_size=None):
    """Get coordinates and dimensions of fixed-size selection box"""
    box_size = int(1024 * 0.25)
    
    if point is None and image_size is not None:
        width, height = image_size
        x1 = (width - box_size) // 2
        y1 = (height - box_size) // 2
    else:
        x1, y1 = point
        # Ensure selection box doesn't extend beyond image boundaries
        if image_size:
            width, height = image_size
            x1 = max(0, min(x1 - box_size//2, width - box_size))
            y1 = max(0, min(y1 - box_size//2, height - box_size))
    
    return (x1, y1, box_size, box_size)

def match_background_to_shirt(design_image, shirt_image):
    """Adjust design image background color to match shirt"""
    # Ensure images are in RGBA mode
    design_image = design_image.convert("RGBA")
    shirt_image = shirt_image.convert("RGBA")
    
    # Get shirt background color (assuming top-left corner color)
    shirt_bg_color = shirt_image.getpixel((0, 0))
    
    # Get design image data
    datas = design_image.getdata()
    newData = []
    
    for item in datas:
        # If pixel is transparent, keep it unchanged
        if item[3] == 0:
            newData.append(item)
        else:
            # Adjust non-transparent pixel background color to match shirt
            newData.append((shirt_bg_color[0], shirt_bg_color[1], shirt_bg_color[2], item[3]))
    
    design_image.putdata(newData)
    return design_image

# 添加一个用于改变T恤颜色的函数
def change_shirt_color(image, color_hex, apply_texture=False, fabric_type=None):
    """改变T恤的颜色，可选择应用面料纹理"""
    # 判断是否是应用了纹理的图像，如果是，则重新从原始图像开始处理
    # 这可以确保每次更改颜色时都从原始状态开始，而不是在已应用纹理的图像上再次修改
    if hasattr(st.session_state, 'original_base_image') and st.session_state.original_base_image is not None:
        # 使用原始白色T恤图像作为基础
        image = st.session_state.original_base_image.copy()
    
    # 转换十六进制颜色为RGB
    color_rgb = tuple(int(color_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    
    # 创建副本避免修改原图
    colored_image = image.copy().convert("RGBA")
    
    # 获取图像数据
    data = colored_image.getdata()
    
    # 创建新数据
    new_data = []
    # 白色阈值 - 调整这个值可以控制哪些像素被视为白色/浅色并被改变
    threshold = 200
    
    for item in data:
        # 判断是否是白色/浅色区域 (RGB值都很高)
        if item[0] > threshold and item[1] > threshold and item[2] > threshold and item[3] > 0:
            # 保持原透明度，改变颜色
            new_color = (color_rgb[0], color_rgb[1], color_rgb[2], item[3])
            new_data.append(new_color)
        else:
            # 保持其他颜色不变
            new_data.append(item)
    
    # 更新图像数据
    colored_image.putdata(new_data)
    
    # 如果需要应用纹理
    if apply_texture and fabric_type:
        return apply_fabric_texture(colored_image, fabric_type)
    
    return colored_image

def get_preset_logos():
    """获取预设logo文件夹中的所有图片"""
    # 确保os模块在这个作用域内可用
    import os
    
    logos_dir = "logos"
    preset_logos = []
    
    # 检查logos文件夹是否存在
    if not os.path.exists(logos_dir):
        os.makedirs(logos_dir)
        return preset_logos
    
    # 获取所有支持的图片文件
    for file in os.listdir(logos_dir):
        if file.lower().endswith(('.png', '.jpg', '.jpeg')):
            preset_logos.append(os.path.join(logos_dir, file))
    
    return preset_logos

# AI Customization Group design page
def show_high_complexity_general_sales():
    """显示高复杂度一般销售页面"""
    # 初始化T恤定制服务
    tshirt_service = TshirtCustomizationService()
    
    # 设置页面标题和说明
    st.title("🎨 T恤定制设计")
    st.markdown("""
    ### 创建您的专属T恤设计
    使用我们的AI辅助设计工具，创建独特的T恤设计。您可以：
    - 选择T恤颜色和面料
    - 添加自定义文字
    - 上传或生成Logo
    - 调整设计位置和大小
    """)
    
    # 创建两列布局
    col1, col2 = st.columns([1, 1])
    
    with col1:
        # 显示当前设计预览
        if hasattr(st.session_state, 'current_image') and st.session_state.current_image is not None:
            st.markdown("### 设计预览")
            st.image(st.session_state.current_image, use_column_width=True)
        else:
            st.markdown("### 设计预览")
            st.image("tshirt_templates/tshirt_template.png", use_column_width=True)
    
    with col2:
        # 设计选项
        st.markdown("### 设计选项")
        
        # 颜色选择
        with st.expander("🎨 颜色选择", expanded=True):
            st.markdown("#### 选择T恤颜色")
            
            # 显示AI建议的颜色
            if hasattr(st.session_state, 'ai_suggested_colors') and st.session_state.ai_suggested_colors:
                st.markdown("**AI推荐颜色:**")
                for i, color in enumerate(st.session_state.ai_suggested_colors):
                    if st.button(f"使用建议颜色 {i+1}: {color}", key=f"use_color_{i}"):
                        st.session_state.shirt_color_hex = color
                        st.session_state.current_applied_color = color
                        st.rerun()
            
            # 自定义颜色选择
            custom_color = st.color_picker("选择自定义颜色", 
                                         value=st.session_state.shirt_color_hex if hasattr(st.session_state, 'shirt_color_hex') else "#FFFFFF")
            
            if custom_color != st.session_state.shirt_color_hex if hasattr(st.session_state, 'shirt_color_hex') else True:
                st.session_state.shirt_color_hex = custom_color
                st.session_state.current_applied_color = custom_color
                st.rerun()
        
        # 文字设计
        with st.expander("📝 文字设计", expanded=True):
            st.markdown("#### 添加文字到设计")
            
            # 显示AI建议的文字
            if hasattr(st.session_state, 'ai_suggested_texts') and st.session_state.ai_suggested_texts:
                st.markdown("**AI推荐文字:**")
                for i, text in enumerate(st.session_state.ai_suggested_texts):
                    if st.button(f"使用建议文字 {i+1}: {text}", key=f"use_text_{i}"):
                        st.session_state.applied_text = text
                        st.session_state.current_text_info = {
                            "text": text,
                            "font": "Arial",
                            "size": 30,
                            "color": "#000000"
                        }
                        st.rerun()
            
            # 自定义文字输入
            text_input = st.text_input("输入文字", 
                                     value=st.session_state.applied_text if hasattr(st.session_state, 'applied_text') else "",
                                     placeholder="输入要添加的文字...")
            
            if text_input:
                st.session_state.applied_text = text_input
                st.session_state.current_text_info = {
                    "text": text_input,
                    "font": "Arial",
                    "size": 30,
                    "color": "#000000"
                }
                st.rerun()
        
        # Logo设计
        with st.expander("🖼️ Logo Design", expanded=True):
            st.markdown("#### Add Logo to Your Design")
            
            # 显示AI建议的Logo
            if hasattr(st.session_state, 'ai_suggested_logos') and st.session_state.ai_suggested_logos:
                st.markdown("**AI Recommended Logos:**")
                
                # 显示当前Logo（如果有）
                if hasattr(st.session_state, 'generated_logo') and st.session_state.generated_logo is not None:
                    st.markdown("**Current Logo:**")
                    st.image(st.session_state.generated_logo, width=200)
                    
                    # 显示Logo描述
                    if hasattr(st.session_state, 'logo_prompt'):
                        st.markdown(f"*Description: {st.session_state.logo_prompt}*")
                
                # 显示其他AI建议的Logo选项
                if len(st.session_state.ai_suggested_logos) > 1:
                    st.markdown("**Other Logo suggestions:**")
                    for i, logo_desc in enumerate(st.session_state.ai_suggested_logos[1:], 1):
                        if st.button(f"Use suggestion {i}: {logo_desc[:50]}...", key=f"use_logo_suggestion_{i}"):
                            with st.spinner("Generating Logo..."):
                                try:
                                    # 构建完整的提示词
                                    full_prompt = f"Create a Logo design: {logo_desc}. Requirements: 1. Use a simple design 2. Suitable for printing 3. Background transparent 4. Clear and recognizable pattern"
                                    
                                    # 调用DALL-E生成图像
                                    logo_image = generate_vector_image(full_prompt)
                                    
                                    if logo_image:
                                        # 保存生成的Logo
                                        st.session_state.generated_logo = logo_image
                                        # 保存Logo提示词
                                        st.session_state.logo_prompt = logo_desc
                                        # 标记为用户选择的Logo
                                        st.session_state.logo_auto_generated = False
                                        st.success("Logo generated successfully!")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"Error generating Logo: {str(e)}")
            
            # 添加自定义Logo生成功能
            st.markdown("**Generate Custom Logo:**")
            logo_prompt = st.text_input("Describe your logo design", 
                                      value=st.session_state.logo_prompt if hasattr(st.session_state, 'logo_prompt') else "",
                                      placeholder="e.g., a minimalist mountain logo, a modern abstract pattern, a simple geometric shape...")
            
            if st.button("Generate Logo"):
                if logo_prompt:
                    with st.spinner("Generating logo with AI..."):
                        try:
                            # 构建完整的提示词
                            full_prompt = f"Create a Logo design: {logo_prompt}. Requirements: 1. Use a simple design 2. Suitable for printing 3. Background transparent 4. Clear and recognizable pattern"
                            
                            # 调用DALL-E生成Logo
                            generated_logo = generate_vector_image(full_prompt)
                            
                            if generated_logo:
                                # 保存生成的Logo
                                temp_filename = f"generated_logo_{uuid.uuid4()}.png"
                                temp_path = os.path.join("logos", temp_filename)
                                generated_logo.save(temp_path)
                                
                                # 更新Logo信息
                                st.session_state.selected_preset_logo = temp_path
                                st.session_state.applied_logo = {
                                    "source": "ai",
                                    "path": temp_path,
                                    "size": 25,
                                    "position": "Center",
                                    "opacity": 100
                                }
                                
                                # 应用Logo到T恤
                                try:
                                    # 获取当前T恤图像
                                    if st.session_state.final_design is not None:
                                        new_design = st.session_state.final_design.copy()
                                    else:
                                        new_design = st.session_state.base_image.copy()
                                    
                                    # 获取图像尺寸
                                    img_width, img_height = new_design.size
                                    
                                    # 定义T恤前胸区域
                                    chest_width = int(img_width * 0.95)
                                    chest_height = int(img_height * 0.6)
                                    chest_left = (img_width - chest_width) // 2
                                    chest_top = int(img_height * 0.2)
                                    
                                    # 调整Logo大小
                                    logo_size_factor = 25 / 100  # 默认25%大小
                                    logo_width = int(chest_width * logo_size_factor * 0.5)
                                    logo_height = int(logo_width * generated_logo.height / generated_logo.width)
                                    logo_resized = generated_logo.resize((logo_width, logo_height), Image.LANCZOS)
                                    
                                    # 计算居中位置
                                    logo_x = chest_left + (chest_width - logo_width) // 2
                                    logo_y = chest_top + (chest_height - logo_height) // 2
                                    
                                    # 粘贴Logo到设计
                                    new_design.paste(logo_resized, (logo_x, logo_y), logo_resized)
                                    
                                    # 更新设计和预览
                                    st.session_state.final_design = new_design
                                    st.session_state.current_image = new_design.copy()
                                    
                                    st.success("Logo generated and applied successfully!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error applying logo to design: {str(e)}")
                            else:
                                st.error("Failed to generate logo. Please try again.")
                        except Exception as e:
                            st.error(f"Error generating logo: {str(e)}")
                else:
                    st.warning("Please enter a logo description.")
            
            # 如果已有Logo，显示修改功能
            if hasattr(st.session_state, 'generated_logo') and st.session_state.generated_logo is not None:
                # Logo调整选项
                st.markdown("**Adjust Logo:**")
                logo_size = st.slider("Logo size (%)", 5, 50, st.session_state.applied_logo["size"] if hasattr(st.session_state, 'applied_logo') else 25)
                
                position_options = ["Top-left", "Top-center", "Top-right", "Center", "Bottom-left", "Bottom-center", "Bottom-right"]
                logo_position = st.selectbox("Logo position", position_options, 
                                           index=position_options.index(st.session_state.applied_logo["position"]) if hasattr(st.session_state, 'applied_logo') and st.session_state.applied_logo["position"] in position_options else 3)
                
                logo_opacity = st.slider("Logo opacity (%)", 10, 100, st.session_state.applied_logo["opacity"] if hasattr(st.session_state, 'applied_logo') else 100)
                
                if st.button("Apply logo settings"):
                    # 更新Logo设置
                    st.session_state.applied_logo = {
                        "source": st.session_state.applied_logo["source"] if hasattr(st.session_state, 'applied_logo') else "ai",
                        "path": st.session_state.selected_preset_logo if hasattr(st.session_state, 'selected_preset_logo') else None,
                        "size": logo_size,
                        "position": logo_position,
                        "opacity": logo_opacity
                    }
                    
                    # 重新应用Logo到T恤
                    try:
                        # 获取当前T恤图像
                        if st.session_state.final_design is not None:
                            new_design = st.session_state.final_design.copy()
                        else:
                            new_design = st.session_state.base_image.copy()
                        
                        # 获取图像尺寸
                        img_width, img_height = new_design.size
                        
                        # 定义T恤前胸区域
                        chest_width = int(img_width * 0.95)
                        chest_height = int(img_height * 0.6)
                        chest_left = (img_width - chest_width) // 2
                        chest_top = int(img_height * 0.2)
                        
                        # 加载当前Logo
                        current_logo = st.session_state.generated_logo
                        
                        # 调整Logo大小
                        logo_size_factor = logo_size / 100
                        logo_width = int(chest_width * logo_size_factor * 0.5)
                        logo_height = int(logo_width * current_logo.height / current_logo.width)
                        logo_resized = current_logo.resize((logo_width, logo_height), Image.LANCZOS)
                        
                        # 计算位置
                        if logo_position == "Center":
                            logo_x = chest_left + (chest_width - logo_width) // 2
                            logo_y = chest_top + (chest_height - logo_height) // 2
                        elif logo_position == "Top-left":
                            logo_x = chest_left + 10
                            logo_y = chest_top + 10
                        elif logo_position == "Top-right":
                            logo_x = chest_left + chest_width - logo_width - 10
                            logo_y = chest_top + 10
                        elif logo_position == "Bottom-left":
                            logo_x = chest_left + 10
                            logo_y = chest_top + chest_height - logo_height - 10
                        elif logo_position == "Bottom-right":
                            logo_x = chest_left + chest_width - logo_width - 10
                            logo_y = chest_top + chest_height - logo_height - 10
                        else:
                            # 默认居中
                            logo_x = chest_left + (chest_width - logo_width) // 2
                            logo_y = chest_top + (chest_height - logo_height) // 2
                        
                        # 设置透明度
                        if logo_opacity < 100:
                            logo_data = logo_resized.getdata()
                            new_data = []
                            for item in logo_data:
                                r, g, b, a = item
                                new_a = int(a * logo_opacity / 100)
                                new_data.append((r, g, b, new_a))
                            logo_resized.putdata(new_data)
                        
                        # 粘贴Logo到设计
                        new_design.paste(logo_resized, (logo_x, logo_y), logo_resized)
                        
                        # 更新设计和预览
                        st.session_state.final_design = new_design
                        st.session_state.current_image = new_design.copy()
                        
                        st.success("Logo settings applied successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error applying logo settings: {str(e)}")
    
    # Return to main interface button
    if st.button("Back to main page"):
        # 清空所有设计相关的状态
        keys_to_clear = [
            # 基本图像状态
            'base_image', 'current_image', 'current_box_position', 
            'original_base_image', 'final_design',
            
            # 颜色和面料相关
            'shirt_color_hex', 'current_applied_color', 'fabric_type',
            'current_applied_fabric', 'ai_suggested_colors', 'ai_suggested_fabrics',
            
            # AI建议相关
            'ai_suggestions', 'ai_suggested_texts', 'ai_suggested_logos',
            
            # 文字相关
            'applied_text', 'current_text_info', 'ai_text_suggestion',
            'temp_text_selection', 'text_position', 'text_size_info',
            
            # Logo相关
            'applied_logo', 'generated_logo', 'logo_auto_generated',
            'show_generated_logo', 'logo_prompt', 'selected_preset_logo',
            
            # 调试信息
            'font_debug_info', 'tshirt_size', 'design_area',
            'loaded_font_path', 'using_fallback_text'
        ]
        
        # 循环清除所有状态
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        
        # 保留用户信息和实验组，但清除当前页面状态
        st.session_state.page = "welcome"
        
        # 添加成功提示
        st.success("所有设计已清除，正在返回主页...")
        st.rerun()
