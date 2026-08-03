require 'securerandom'
require 'digest'
require 'json'

class UserSessionManager
  SESSION_MUTEX = Mutex.new

  @@active_sessions = {}
  @@session_data = {}

  def initialize
    @timeout_seconds = 3600
  end

  def create_session(user_id, metadata = {})
    session_token = generate_token(user_id)
    current_time = Time.now

    SESSION_MUTEX.synchronize do
      @@active_sessions[session_token] = {
        user_id: user_id,
        created_at: current_time,
        last_accessed: current_time,
        metadata: metadata
      }

      @@session_data[session_token] = []
    end

    session_token
  end

  def validate_session(token)
    current_time = Time.now

    SESSION_MUTEX.synchronize do
      session = @@active_sessions[token]
      return false unless session

      if expired_session?(session, current_time)
        remove_session(token)
        return false
      end

      session[:last_accessed] = current_time
      true
    end
  end

  def get_user_id(token)
    SESSION_MUTEX.synchronize do
      session = @@active_sessions[token]
      session[:user_id] if session
    end
  end

  def store_session_data(token, data)
    SESSION_MUTEX.synchronize do
      @@session_data[token] << data if @@active_sessions.key?(token)
    end
  end

  def get_session_data(token)
    SESSION_MUTEX.synchronize do
      (@@session_data[token] || []).dup
    end
  end

  def destroy_session(token)
    SESSION_MUTEX.synchronize do
      remove_session(token)
    end
  end

  def cleanup_expired_sessions
    current_time = Time.now

    SESSION_MUTEX.synchronize do
      expired_tokens = @@active_sessions.each_with_object([]) do |(token, session), tokens|
        tokens << token if expired_session?(session, current_time)
      end

      expired_tokens.each { |token| remove_session(token) }
    end
  end

  def get_all_active_sessions
    SESSION_MUTEX.synchronize do
      @@active_sessions.transform_values(&:dup)
    end
  end

  private

  def expired_session?(session, current_time)
    current_time - session[:created_at] > @timeout_seconds
  end

  def remove_session(token)
    @@active_sessions.delete(token)
    @@session_data.delete(token)
  end

  def generate_token(user_id)
    timestamp = Time.now.to_i
    random_part = SecureRandom.hex(8)
    "#{user_id}_#{timestamp}_#{random_part}"
  end
end
