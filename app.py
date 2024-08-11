import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from duckduckgo_search import DDGS
import yt_dlp
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"),
              logging.StreamHandler()])
logger = logging.getLogger(__name__)

# Use environment variable for bot token
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise ValueError(
        "No token provided. Set the TELEGRAM_BOT_TOKEN environment variable.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Start command received from user {update.effective_user.id}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hello! Send me a search query for videos from any website.")


async def search_duckduckgo(query):
    logger.info(f"Searching DuckDuckGo for: {query}")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"{query} video", max_results=10))
        logger.info(f"Found {len(results)} results")
        return results
    except Exception as e:
        logger.error(f"Error in DuckDuckGo search: {str(e)}", exc_info=True)
        return []


async def get_pexels_videos(query):
    url = f"https://www.pexels.com/search/videos/{query}/"
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')
        video_elements = soup.find_all('article', class_='PhotoItem')

        videos = []
        for element in video_elements[:5]:  # Limit to 5 results
            video_url = element.find('a', class_='PhotoItem__link')['href']
            title = element.find('img')['alt']
            videos.append({
                'title': title,
                'href': f"https://www.pexels.com{video_url}"
            })
        return videos
    except Exception as e:
        logger.error(f"Error fetching Pexels videos: {str(e)}", exc_info=True)
        return []


async def search_and_send_links(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    logger.info(
        f"Received search query: {query} from user {update.effective_user.id}")
    await context.bot.send_message(chat_id=update.effective_chat.id,
                                   text=f"Searching for: {query}")

    if 'pexels' in query.lower():
        results = await get_pexels_videos(query.replace('pexels', '').strip())
    else:
        results = await search_duckduckgo(query)

    logger.info(f"Search results: {results}")

    if not results:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No results found. Please try a different search query.")
        return

    video_results = []
    for result in results:
        if any(ext in result['href'].lower() for ext in ['.mp4', '.avi', '.mov', '.flv', '.wmv']) or \
           any(site in result['href'].lower() for site in ['youtube.com', 'vimeo.com', 'dailymotion.com', 'twitch.tv', 'pexels.com', 'pixabay.com']) or \
           any(keyword in result['title'].lower() for keyword in ['video', 'clip', 'footage']):
            video_results.append(result)
        if len(video_results) == 5:
            break

    if not video_results:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No video results found. Please try a different search query."
        )
        return

    for result in video_results:
        title = result.get('title', 'Untitled')
        url = result.get('href')

        keyboard = [[
            InlineKeyboardButton("Download", callback_data=f"download_{url}")
        ], [InlineKeyboardButton("Watch Online", url=url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        caption = f"Title: {title}\n\nClick 'Download' to get the video or 'Watch Online' to view it in your browser."

        try:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=f"{caption}\n\nURL: {url}",
                                           reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}", exc_info=True)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=
        "Search completed. If you want to search again, just send a new query."
    )


async def download_video(url):
    logger.info(f"Attempting to download video from: {url}")
    ydl_opts = {
        'outtmpl': '%(title)s.%(ext)s',
        'format': 'best',
        'noplaylist': True,
        'no_warnings': True,
        'ignoreerrors': False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info,
                                           url,
                                           download=True)
            filename = ydl.prepare_filename(info)
        logger.info(f"Video downloaded: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}", exc_info=True)
        return None


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("download_"):
        url = query.data[9:]  # Remove "download_" prefix
        await query.edit_message_reply_markup(reply_markup=None)

        status_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Downloading video... Please wait.")

        filename = await download_video(url)
        if filename and os.path.exists(filename):
            try:
                file_size = os.path.getsize(filename)
                if file_size > 50 * 1024 * 1024:  # If file is larger than 50MB
                    await status_message.edit_text(
                        "The video is too large to send via Telegram. You can download it using this link:"
                    )
                    with open(filename, 'rb') as file:
                        uploaded_file = await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=file,
                            filename=os.path.basename(filename))
                        file_id = uploaded_file.document.file_id
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text=
                            f"https://api.telegram.org/file/bot{TOKEN}/{file_id}"
                        )
                else:
                    with open(filename, 'rb') as video_file:
                        await context.bot.send_video(
                            chat_id=query.message.chat_id,
                            video=video_file,
                            caption="Here's your requested video!")
                    await status_message.delete()
            except Exception as e:
                logger.error(f"Error sending video: {str(e)}", exc_info=True)
                await status_message.edit_text(
                    f"Error sending video: {str(e)}. You can try watching it online instead."
                )
            finally:
                os.remove(filename)  # Clean up the downloaded file
        else:
            await status_message.edit_text(
                "Sorry, I couldn't download the video. It might not be available or the website might be unsupported. You can try watching it online."
            )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=
            "An error occurred while processing your request. Please try again later."
        )


if __name__ == '__main__':
    logger.info("Starting bot...")
    application = ApplicationBuilder().token(TOKEN).build()

    start_handler = CommandHandler('start', start)
    search_handler = MessageHandler(filters.TEXT & ~filters.COMMAND,
                                    search_and_send_links)
    button_handler = CallbackQueryHandler(button_callback)

    application.add_handler(start_handler)
    application.add_handler(search_handler)
    application.add_handler(button_handler)
    application.add_error_handler(error_handler)

    logger.info("Bot is ready. Starting polling...")
    application.run_polling()
